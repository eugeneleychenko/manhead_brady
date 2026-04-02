# Merch Prediction Model: Testing Results & How-To Guide

**Prepared by**: Eugene Leychenko
**Date**: March 5, 2026
**Band Tested**: Air Supply (7 completed shows, Dec 2025 - Feb 2026)

---

## Summary

We tested two merch sales prediction models against 7 real Air Supply shows where we already know the actual sales numbers. The goal was to see how close each model's predictions come to reality.

**Bottom line**: Both models over-predict — they consistently forecast more sales than actually happen. The new model (built by Ashling Partners) is closer to reality than the current model, but neither is accurate enough to rely on without further calibration.

---

## What We Tested

We took 7 Air Supply shows that already happened and ran them through both prediction models. Then we compared the predicted merch units to what actually sold.

| Show Date | City | Attendance | What Actually Sold |
|-----------|------|------------|-------------------|
| Dec 17, 2025 | Toronto | 3,844 | 198 units |
| Dec 19, 2025 | Tsuut'ina | 2,347 | 173 units |
| Dec 20, 2025 | Edmonton | 4,423 | 230 units |
| Feb 13, 2026 | San Jose | 2,634 | 260 units |
| Feb 14, 2026 | Rancho Mirage | 1,800 | 128 units |
| Feb 15, 2026 | Valley Center | 1,900 | 164 units |
| Feb 22, 2026 | Maravillas | 2,500 | 36 units |

---

## Results: Current Model vs Ashling Model

### Per-Show Predictions

| Show | Actual Units | Current Model Predicted | Ashling Model Predicted | Which Was Closer? |
|------|-------------|------------------------|------------------------|-------------------|
| Toronto | 198 | 1,139 | 639 | Ashling |
| Tsuut'ina | 173 | 809 | 611 | Ashling |
| Edmonton | 230 | 886 | 730 | Ashling |
| San Jose | 260 | 702 | 487 | Ashling |
| Rancho Mirage | 128 | 1,204 | 668 | Ashling |
| Valley Center | 164 | 1,169 | 683 | Ashling |
| Maravillas | 36 | 532 | 339 | Ashling |

### Per-Head Revenue ($/Head)

This is the revenue generated per attendee — the key metric for planning.

| Show | Actual $/Head | Current Model $/Head | Ashling Model $/Head |
|------|--------------|---------------------|---------------------|
| Toronto | $2.11 | $13.41 | $7.43 |
| Tsuut'ina | $2.74 | $13.69 | $10.51 |
| Edmonton | $1.90 | $8.18 | $6.66 |
| San Jose | $3.44 | $10.32 | $7.16 |
| Rancho Mirage | $2.90 | $27.37 | $15.41 |
| Valley Center | $3.45 | $25.80 | $15.32 |
| Maravillas | $0.67 | $9.94 | $6.33 |

### Overall Accuracy

| Metric | Current Model | Ashling Model |
|--------|--------------|---------------|
| Average error (units) | 590% over | 337% over |
| Average $/Head error | $13.07 over | $7.37 over |
| Shows where it was closer | 0 out of 7 | 7 out of 7 |

**The Ashling model won on every single show**, but it still over-predicts by roughly 2-8x.

---

## Key Takeaways

1. **Both models over-predict significantly.** If either model says you'll sell 500 units, you might actually sell 100-200. This is important context for any inventory or staffing decisions based on these predictions.

2. **The Ashling model is consistently closer.** It cut the error roughly in half compared to the current model. On average, its $/head predictions are off by $7.37 vs $13.07 for the current model.

3. **Neither model should be treated as a point estimate.** Use the predictions as a directional signal ("this show will probably sell more than that show") rather than an exact number to order inventory against.

4. **More testing with other bands would help.** We only tested Air Supply. The models may perform differently for higher-energy bands (Deftones, Jelly Roll) where merch sales per head tend to be higher.

---

## How the Ashling Model Works

The Ashling model uses more data points than the current model to make predictions:

**Current Model Inputs** (what it knows about):
- Band name and genre
- Show date and venue
- Attendance
- Product type, size, and price

**Ashling Model Inputs** (everything above, plus):
- Historical weather at the venue (temperature, rain, snow)
- Band's Spotify monthly listeners
- Band's Instagram followers
- Venue capacity
- Whether the show is on a weekend or holiday

The additional data is meant to help the model understand context — a cold rainy Tuesday show at a half-full venue will sell differently than a sunny Saturday at a sold-out arena.

---

## How to Run a Prediction (Ashling Model)

Once deployed, the Ashling model will be a web app accessible via URL (similar to how the current model lives at mh-predict.streamlit.app). Here's the workflow:

### What You Need

Before running a prediction, you need two files from atVenu:

1. **Sales Report** (one per show date)
   - atVenu > Artist > Reports > Sales Report
   - Select the specific tour and date
   - Export as CSV

2. **Tour Summary**
   - atVenu > Artist > Reports > Tour Summary
   - Select the tour and date range
   - Export as CSV

### Steps

**Step 1: Add Artist Data** (only needed for new bands)
- If the band hasn't been run through the system before, enter their name, Instagram follower count, and genre
- Skip this step for bands already in the system

**Step 2: Format and Consolidate Data**
- Upload the Sales Report and Tour Summary CSVs
- Click "Run consolidation pipeline"
- The system will automatically look up weather data, Spotify listeners, and venue details
- This produces an enriched file with all the data the model needs

**Step 4: Run Predictions**
- Upload the enriched file from Step 2
- Click "Run prediction"
- The results show predicted units for each product/size combination
- Download the results as CSV

**Step 5: Revenue Per Head** (optional)
- Upload the Step 4 output
- Gets you the predicted $/head for each show

### Output

The prediction gives you:
- **Predicted units per product per size** (e.g., "Balloon Arch Tee, Size M: 26 units")
- **Percentage of category sales** (e.g., "this tee makes up 6% of all T-shirt sales")
- **$/Head** (e.g., "$7.43 revenue per attendee")

---

## What's Next

- **Deploy the Ashling model** to a hosted URL so the team can access it without local setup
- **Test with more bands** — run the same backtest with Deftones, B-52's, Jelly Roll, and others to see if accuracy varies by genre
- **Work with Ashling on calibration** — share these over-prediction findings so they can adjust the model
- **Establish a rule of thumb** — until the model is better calibrated, consider dividing predictions by 3-4x as a rough adjustment based on the Air Supply results

---

## Appendix: Test Methodology

For anyone curious about how the tests were run:

1. We collected actual sales data (Sales Reports) and show data (Tour Summaries) from atVenu for 7 completed Air Supply shows
2. We formatted the data the same way each model expects it
3. We sent the data through each model's prediction API
4. We compared predicted quantities to actual quantities sold
5. We verified the automated comparison by manually running one show (Toronto, Dec 17) through both model UIs and confirming the numbers matched exactly

All raw data, scripts, and results are saved in the `Mar_26_testing/` folder of the project repository.
