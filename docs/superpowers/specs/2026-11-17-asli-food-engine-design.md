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
- Converts household units to grams. v1 units: roti/chapati, katori (bowl), plate, cup, glass, piece, tablespoon, serving.
- Gram values come from INDB's per-serving sizes where available, otherwise from a small table measured and reviewed by the team, with the source recorded per row.

### 4.5 Calculator
- grams × (nutrient per 100 g) / 100 for each dish, summed per meal.
- Each value carries a low-to-high range, not a single falsely precise number. v1 rule: each dish has a confidence band (high, medium, low) taken from the recognizer and lowered one step if the match needed confirmation. The gram estimate is widened by ±15% (high), ±30% (medium) or ±50% (low), and nutrients are computed at both ends. These starting percentages are tuned against the evaluation set (section 7).
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

## 9. Decisions to make during planning

- Which Claude model to use by default, chosen after checking current pricing and vision quality. The model is configurable.
- The match-score threshold in 4.3, set using the evaluation set.

## 10. Requirement before commercial launch

- The INDB GitHub repository has no licence file (checked 2026-11-17), which by default grants no permission for commercial use. Before launch, obtain written permission from the INDB authors or replace the data. Development and evaluation can proceed meanwhile; the import script (4.2) keeps the data source swappable.
