# Asli Food Analysis Engine — Design (v1)

Date: 2026-11-17
Status: Draft for review

## 1. Purpose

Asli is a clip-on camera for ordinary glasses that passively tracks what a person eats, plus a phone app that shows daily protein, water and macro progress. The food analysis engine is the core service: it turns a meal (photo and/or text) into dishes, portions and macros for Indian food. The phone app, and later the clip, call it.

## 2. Scope

### In v1
- Input: one meal as a photo, a text description, or both. Voice is converted to text by the phone app before it reaches the engine.
- Output: per-dish name, matched databank entry, portion (household units and grams), protein, carbohydrate, fat, fibre, energy (kcal), confidence, and a meal total.
- Uncertain dishes are flagged with candidate choices so the app can ask the user one question.

### Not in v1 (later work, built on v1)
- Before/after plate comparison to measure how much was actually eaten.
- Splitting one family meal across several people.
- Water tracking.
- Receiving photos from the clip (the device link is a separate component).
- Accounts, sync and long-term storage (backend is a separate component).
- Our own trained recognition model (replaces the recognizer later; see 4.1).

## 3. Approach

A vision AI model identifies dishes and estimates portions in household units. Deterministic code matches each dish to the Indian Nutrient Databank (INDB) and calculates nutrients. The AI model never produces nutrient numbers itself, so results are consistent and traceable to a cited source.

Language: Python. Web framework: FastAPI.

Data source: Indian Nutrient Databank, 1,014 cooked Indian recipes with values per 100 g and per serving, built on ICMR-NIN food composition tables. Repository: https://github.com/lindsayjaacks/Indian-Nutrient-Databank-INDB-

## 4. Components

Each component has one job and a narrow interface, so it can be tested and replaced on its own.

### 4.1 Recognizer
- Input: image bytes (optional) and text (optional).
- Output: list of `DishGuess` = {name, alternative names, portion unit, quantity, confidence}, or a status of `no_food` / `unclear_image`.
- Defined as an interface (`Recognizer`). v1 implementation calls the Claude API with structured output. A future implementation can use our own trained model without changing other components.
- The AI model is given the list of allowed portion units (see 4.4) and must use one of them.

### 4.2 Food database
- INDB loaded into a local SQLite database at build time by an import script.
- Alias table mapping alternative names to INDB entries (for example "chole" to chana masala, Hindi and regional spellings, common sabzi variants). Starts small and grows from the unmatched-dish log (5.2).

### 4.3 Matcher
- Input: a `DishGuess`. Output: a matched INDB entry with a match score, or `unmatched`.
- Step 1: exact and fuzzy match on names and aliases.
- Step 2: if the best score is below a threshold, send the AI model the five closest INDB entries and require it to pick one of them or answer "none". The engine never creates a dish that is not in the databank.
- If the final match is still weak, return the top three candidates for user confirmation.

### 4.4 Portion converter
- Converts household units to grams. v1 units: serving, bowl (katori), plate, piece (roti, idli, dosa and other countable items), cup, glass, tablespoon, teaspoon.
- INDB serving sizes are inconsistent for containers (checked 2026-11-17: a "bowl" of poha is 55 g, a "bowl" of paneer kofta curry is 701 g, because some servings are a whole recipe), but per-piece weights for countable foods are reliable (chapati 36 g, idli 25 g). So the rule is:
  1. bowl, plate, cup, glass, tablespoon, teaspoon: grams from a household-units table (`data/household_units.csv`) with the source recorded per row. Values not yet measured by the team are marked provisional.
  2. piece, for a dish whose INDB serving unit is countable: INDB per-piece weight.
  3. serving: INDB serving weight.
  4. Anything else (for example "piece" of a curry): INDB serving weight if it exists, otherwise 100 g, and confidence is lowered one step.

### 4.5 Calculator
- grams × (nutrient per 100 g) / 100 for each dish, summed per meal.
- Each value carries a low-to-high range, not a single falsely precise number. v1 rule: each dish has a confidence band (high, medium, low) taken from the recognizer, lowered one step if the AI had to choose the databank entry (4.3 step 2), and one more step if the portion used the fallback rule (4.4 rule 4). The gram estimate is widened by ±15% (high), ±30% (medium) or ±50% (low), and nutrients are computed at both ends. These starting percentages are tuned against the evaluation set (section 7).
- Unmatched dishes are excluded from totals and listed separately.

### 4.6 API
- `POST /analyze`: multipart request with an optional image and optional text. Returns JSON with status, dishes, totals and items needing confirmation.
- `GET /health`: liveness check.

## 5. Behaviour when things go wrong

### 5.1 Response statuses
| Situation | Behaviour |
|---|---|
| No food in photo | status `no_food`, no dishes, no guess |
| Blurry or dark photo | status `unclear_image`, no guess |
| Uncertain match | dish flagged `needs_confirmation` with top 3 candidates |
| Dish not in databank | dish returned as `unmatched`, excluded from totals |
| AI service error or timeout | one retry, then status `error` with a message so the app can fall back to manual logging |
| Neither image nor text sent | HTTP 400 |

### 5.2 Unmatched-dish log
Every unmatched dish name is logged with a count. The most frequent entries are the backlog for alias and database additions.

### 5.3 Hidden fats
INDB recipes include standard cooking fat, so totals use recipe defaults. This is a known error source and is reflected in the confidence range.

## 6. Privacy

- Photos are analysed in memory and discarded by default. Only nutrition results are returned.
- Storing photos to improve recognition is a separate, explicit opt-in (not built in v1, but nothing in v1 may store images).
- Designed with India's Digital Personal Data Protection Act in mind.

## 7. Accuracy measurement

- Evaluation set: about 50 real home-cooked meals photographed and weighed by the team, each with a ground-truth record (dishes, grams).
- An evaluation script reports: dish identification accuracy, mean portion error (%), and mean protein error (grams).
- Run after every change to recognition, matching or portions, so changes are judged by numbers.
- The set grows over time into the training dataset for our own model.

## 8. Testing

- Unit tests for matcher, portion converter and calculator using fixed fixture data.
- Recognizer tests replay saved AI responses, so the normal test suite is fast, deterministic and free.
- A small live test suite calls the real AI service and runs only on demand.
- API tests cover each status in 5.1.

## 9. Decisions made during planning

- Default model: `claude-opus-5-5` ($4 / $20 per million input / output tokens, checked 2026-11-17), configurable with `ASLI_MODEL`. Requests use Anthropic's server-side refusal fallback (`fallbacks: "default"`) so a rare safety decline is retried on another model. Whether a cheaper model holds accuracy is decided with the evaluation set (section 7), not assumed.
- Match thresholds in 4.3: accept automatically at a fuzzy score of 90 or more; after the AI chooses, ask the user to confirm when the chosen entry scored below 60. Both are configurable (`ASLI_AUTO_ACCEPT_SCORE`, `ASLI_CONFIRM_SCORE`) and tuned with the evaluation set.
- The raw INDB files and the built database are not committed to git while the licence question (section 10) is open; a download script fetches them.

## 10. Requirement before commercial launch

- The INDB GitHub repository has no licence file (checked 2026-11-17), which by default grants no permission for commercial use. Before launch, obtain written permission from the INDB authors or replace the data. Development and evaluation can proceed meanwhile; the import script (4.2) keeps the data source swappable.
