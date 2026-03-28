# B-Centroid-Diversity Phase 2 — General Consumer Life Seed Examples

## Overview

Phase 1 (complete) added 105 wellness/marketing/business examples to `GistSeedExamples.md`, bringing the total from 113 → 218. Phase 2 adds 105 **general consumer life** examples — everyday adulting, household logistics, personal admin. These are domain-agnostic and create a stable baseline centroid for any type of user.

After Phase 2: each class has ~45 examples across 4 domains (dev, professional, consumer life, general). Total: ~323 examples.

## Files to Read First

| File | Why |
|------|-----|
| `InvertorsDocs/GistSeedExamples.md` | Current seed file (already has Phase 1 merged — 218 examples) |
| `mcp_engine/schema.py` lines 368–436 | `_parse_seed_examples()` parser — must not break |
| `tests/test_schema.py` | Existing tests including Phase 1 diversity test |

## Parser Contract (DO NOT BREAK)

The parser in `mcp_engine/schema.py:_parse_seed_examples()` uses these rules:

1. **Section headers**: `## gist:ClassName` — regex: `^## gist:(\w+)`
2. **Example lines**: `N. "sentence text"` — regex: `^\d+\.\s+"(.+)"`
3. **Everything else is ignored** (description lines, blank lines, markdown formatting)

The merged file MUST preserve this format exactly. All examples must be numbered lines with the sentence in double quotes.

## Implementation

### Phase 1: Append consumer life examples to GistSeedExamples.md

**File: `InvertorsDocs/GistSeedExamples.md`**

For each of the 7 gist class sections, append the following examples after the existing examples. Continue the numbering from where each section currently ends. Each line MUST be formatted as `N. "sentence text"` with double quotes. Add `(L)` domain tag after the closing quote (for "Life" — ignored by parser).

**gist:Restriction** (append after current last example, continue numbering):

```
31. "Rent must be paid by the first of every month to avoid late fees." (L)
32. "The warranty is void if the device is opened or repaired by an unauthorized technician." (L)
33. "Parking is not allowed on the street during street-sweeping hours." (L)
34. "Carry-on luggage must not exceed the airline's weight and size limits." (L)
35. "I am trying to keep my daily sugar intake under 25 grams." (L)
36. "Always lock the deadbolt before going to sleep at night." (L)
37. "The gym requires all members to wipe down equipment after use." (L)
38. "Pets are not allowed on the new living room furniture." (L)
39. "Do not run the dishwasher unless it is completely full." (L)
40. "The doctor advised no heavy lifting for two weeks after the minor surgery." (L)
41. "Library books must be returned within 21 days to avoid fines." (L)
42. "Do not water the indoor plants more than once a week." (L)
43. "The homeowner's association prohibits leaving trash cans out past Monday evening." (L)
44. "I need to restrict my screen time an hour before going to bed." (L)
45. "Never give out your social security number over an unsolicited phone call." (L)
```

**gist:PlannedEvent** (append after current last example, continue numbering):

```
31. "I have a routine dental cleaning scheduled for next Tuesday afternoon." (L)
32. "We are planning a weekend getaway to the mountains next month." (L)
33. "The car needs to go into the shop for an oil change on Friday morning." (L)
34. "I am hosting a dinner party for a few friends this Saturday." (L)
35. "The landlord is scheduled to inspect the apartment's smoke detectors tomorrow." (L)
36. "I plan to deep clean the kitchen appliances over the long weekend." (L)
37. "My annual physical exam is booked for the second week of November." (L)
38. "We are going to a community theater play tomorrow evening." (L)
39. "I'm taking the dog to the vet for his annual vaccinations next week." (L)
40. "I plan to finally organize the hall closet on Sunday afternoon." (L)
41. "The delivery window for the new mattress is scheduled between 1 PM and 4 PM." (L)
42. "I'm meeting a friend for lunch downtown on Wednesday." (L)
43. "We plan to renew our passports before they expire in six months." (L)
44. "The internet technician is coming out to upgrade the router on Thursday." (L)
45. "I am going to start training for a 5k run next Monday." (L)
```

**gist:PhysicalThing** (append after current last example, continue numbering):

```
36. "The spare house keys are kept in the ceramic bowl by the front door." (L)
37. "The title to the car is filed away in the fireproof safe." (L)
38. "The winter coats are stored in the vacuum-sealed bags under the bed." (L)
39. "My primary laptop is currently charging on the home office desk." (L)
40. "The slow cooker is perfect for making warm meals on busy weeknights." (L)
41. "The snow shovel is leaning against the wall in the back of the garage." (L)
42. "I keep my gym bag packed and waiting in the trunk of my car." (L)
43. "The new wireless router was installed right next to the television." (L)
44. "Our emergency preparedness kit is located on the bottom shelf of the pantry." (L)
45. "The vacuum cleaner filter needs to be replaced this month." (L)
46. "The recipe box on the counter holds all my favorite dinner instructions." (L)
47. "The reusable grocery bags are stuffed into the back pocket of the passenger seat." (L)
48. "The digital meat thermometer is in the drawer next to the oven." (L)
49. "My hiking boots are covered in mud from the trail this morning." (L)
50. "The smoke detector in the hallway needs a new nine-volt battery." (L)
```

**gist:Magnitude** (append after current last example, continue numbering):

```
31. "The round-trip flight across the country cost exactly four hundred dollars." (L)
32. "I walked just over ten thousand steps during the neighborhood hike today." (L)
33. "The recipe calls for exactly one and a half cups of all-purpose flour." (L)
34. "It takes about forty-five minutes to drive to the airport with normal traffic." (L)
35. "The new bookshelf took roughly two hours to completely assemble." (L)
36. "I managed to lower my monthly electric bill by 15% this summer." (L)
37. "The temperature dropped by twenty degrees overnight." (L)
38. "The apartment requires a security deposit equal to one month of rent." (L)
39. "We need to buy at least two gallons of paint to finish the living room." (L)
40. "The grocery bill was unusually high this week, totaling almost $200." (L)
41. "My resting heart rate has dropped by five beats per minute since I started running." (L)
42. "The warranty on the new washing machine lasts for exactly five years." (L)
43. "I've read 50 pages of the new novel so far this week." (L)
44. "The speed limit on the residential street is 25 miles per hour." (L)
45. "It will take an estimated three weeks for the custom furniture to be delivered." (L)
```

**gist:Category** (append after current last example, continue numbering):

```
34. "A deductible is the amount you pay out-of-pocket before insurance covers the rest." (L)
35. "Meal prep is the practice of cooking multiple days of food in one single batch." (L)
36. "A streaming service is a platform that delivers movies and shows over the internet." (L)
37. "Preventative maintenance includes routine tasks like changing air filters and checking tire pressure." (L)
38. "A generic brand is a store-label product that is usually cheaper than the name brand." (L)
39. "A utility bill is a recurring monthly charge for essential services like water or electricity." (L)
40. "Compound interest is the interest you earn on both your original money and the accumulated interest." (L)
41. "A warranty is a written guarantee promising to repair or replace an item if necessary." (L)
42. "A layover is a scheduled break between connecting flights during travel." (L)
43. "An emergency fund is a stash of money set aside specifically for unexpected financial surprises." (L)
44. "Batch cooking involves preparing large quantities of a single ingredient to use in different meals." (L)
45. "A security deposit is money given to a landlord to cover potential damage to a rental property." (L)
46. "A fixed-rate mortgage keeps the exact same interest rate for the entire life of the loan." (L)
47. "Organic produce is grown without the use of synthetic pesticides or fertilizers." (L)
48. "A lease agreement is a legal contract outlining the terms under which one party agrees to rent property." (L)
```

**gist:Agent** (append after current last example, continue numbering):

```
31. "The landlord called to say they are repainting the exterior of the building next week." (L)
32. "The mechanic recommended replacing the brake pads before the winter season starts." (L)
33. "A customer service representative helped me process the return for the damaged package." (L)
34. "The neighbor across the street asked if I could water their plants while they are out of town." (L)
35. "The electrician fixed the faulty wiring in the kitchen ceiling fan." (L)
36. "A friend from college is flying into town and staying in the guest bedroom." (L)
37. "The flight attendant requested that all large carry-on bags be checked at the gate." (L)
38. "The veterinarian prescribed a mild antibiotic for the dog's ear infection." (L)
39. "The mail carrier left a package notice slip on the front door this afternoon." (L)
40. "My financial advisor suggested increasing my retirement contributions by two percent." (L)
41. "The plumber unclogged the master bathroom sink in under twenty minutes." (L)
42. "The dentist noted that I need to start flossing more consistently." (L)
43. "A local artist painted the new mural on the side of the community center." (L)
44. "The store manager approved the discount on the slightly scratched display model." (L)
45. "The exterminator comes out quarterly to spray for ants and spiders around the foundation." (L)
```

**gist:Event** (append after current last example, continue numbering):

```
31. "The power went out for three hours during the heavy thunderstorm last night." (L)
32. "I successfully renewed my vehicle registration online this morning." (L)
33. "The refrigerator stopped keeping things cold, so all the food spoiled." (L)
34. "We got caught in a massive traffic jam on the highway for over an hour." (L)
35. "I finally finished putting together the 1000-piece puzzle on the dining table." (L)
36. "The package was delivered two days earlier than the tracking number originally estimated." (L)
37. "I accidentally dropped my phone and cracked the corner of the screen." (L)
38. "The community pool officially opened for the summer season yesterday afternoon." (L)
39. "We discovered a great new hiking trail just a few miles from the house." (L)
40. "I received my annual tax refund via direct deposit yesterday." (L)
41. "The fire alarm went off in the building because someone burned their dinner." (L)
42. "I spilled a cup of water on the rug and had to spot-clean it immediately." (L)
43. "The weather cleared up beautifully just in time for the outdoor concert." (L)
44. "I officially paid off the final balance of my student loans this morning." (L)
45. "A stray dog wandered into the yard, but we safely returned him to his owner." (L)
```

**Important rules:**
- Keep ALL existing examples (both original dev + Phase 1 additions) exactly as-is
- Do NOT modify, reorder, or remove any existing examples
- Keep the existing `## Usage Notes` section at the bottom intact
- Each new example line MUST match the parser regex: `^\d+\.\s+"(.+)"`
- The `(L)` domain tag goes OUTSIDE the closing quote

### Phase 2: Update test thresholds

**File: `tests/test_schema.py`**

Find the existing `test_real_seed_file_has_diverse_examples` test and update the thresholds:

```python
def test_real_seed_file_has_diverse_examples():
    """GistSeedExamples.md has domain-diverse examples (B-centroid-diversity)."""
    from mcp_engine.schema import _parse_seed_examples
    from pathlib import Path

    seed_file = Path(__file__).parent.parent / "InvertorsDocs" / "GistSeedExamples.md"
    if not seed_file.exists():
        pytest.skip("Seed file not found")

    result = _parse_seed_examples(str(seed_file))

    # Every class should have at least 40 examples (original ~15 + professional ~15 + consumer ~15)
    for class_name in ["Restriction", "PlannedEvent", "PhysicalThing",
                       "Magnitude", "Category", "Agent", "Event"]:
        assert class_name in result, f"Missing class: {class_name}"
        assert len(result[class_name]) >= 40, (
            f"gist:{class_name} has only {len(result[class_name])} examples, "
            f"expected >= 40 after Phase 1 + Phase 2 diversity merge"
        )

    # Total should be > 300
    total = sum(len(v) for v in result.values())
    assert total >= 300, f"Total examples {total} < 300"
```

**Do NOT modify any other existing tests.**

### Expected result per section after Phase 2:

| Section | Dev (orig) | Professional (P1) | Consumer Life (P2) | Total |
|---------|-----------|-------------------|-------------------|-------|
| gist:Restriction | 15 | 15 | 15 | 45 |
| gist:PlannedEvent | 15 | 15 | 15 | 45 |
| gist:PhysicalThing | 20 | 15 | 15 | 50 |
| gist:Magnitude | 15 | 15 | 15 | 45 |
| gist:Category | 18 | 15 | 15 | 48 |
| gist:Agent | 15 | 15 | 15 | 45 |
| gist:Event | 15 | 15 | 15 | 45 |
| **Total** | **113** | **105** | **105** | **323** |

## Files to Create

None.

## Files to Modify

| File | Change |
|------|--------|
| `InvertorsDocs/GistSeedExamples.md` | Append 105 consumer life examples across all 7 sections |
| `tests/test_schema.py` | Update `test_real_seed_file_has_diverse_examples` thresholds (>=40 per class, >=300 total) |

## What NOT to Do

- Do NOT modify `mcp_engine/schema.py` — the parser and bootstrap code are unchanged
- Do NOT modify `mcp_engine/loop/step2_gist.py` — thresholds are unchanged
- Do NOT modify any adapter or tool code
- Do NOT renumber or modify existing examples (dev OR Phase 1 professional)
- Do NOT remove any research artifact files

## Verification

1. `python3 -m pytest tests/test_schema.py -v` — all tests pass including updated diversity test
2. `python3 -m pytest tests/ -v` — full suite, 0 new failures
3. `_parse_seed_examples()` returns 7 classes with 40+ examples each
4. Total example count is 323 (113 original + 105 professional + 105 consumer life)
5. All new example lines match parser regex: `^\d+\.\s+"(.+)"`
6. No existing examples were modified or removed
