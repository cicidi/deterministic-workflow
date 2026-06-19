# Home Insurance — End-to-End Scenarios

> Walkthroughs for [workflow.yaml](./workflow.yaml). Trace the full path from user input to completion.
> **Extraction model:** Two parallel LLM calls per turn (narrow state scope + broad full-schema scan), merged by confidence-based resolution.
> **DomainModel invariant:** Only fields that pass Extract → Validate → Transform are written into `collected_fields`. Failed fields never enter the DomainModel.

---

## Scenario 1: Quote & Purchase

### Dialogue Flow

```
User:   "I want a home insurance quote for my apartment"

-- collect_property_info -----------------------------------------
  [LLM → stream]
  "Of course! Let me gather some details about your property.
   What type of property is it? And could you share the address,
   building age, floor area, and construction material?"

User:   "It's an apartment at 88 Nanjing Road, Shanghai 200001.
         Built in 2015, 95 square meters, concrete structure.
         My phone is 138-1234-5678."

  --- EXTRACTION (parallel two-LLM) ---
  LLM 1 (narrow scope — collect_property_info only):
    target: property_type, address, building_age, floor_area, construction_material
    result: { property_type: "apartment" (0.94), address: "88 Nanjing Rd Shanghai 200001" (0.91),
              building_age: "9" (0.87), floor_area: "95" (0.96),
              construction_material: "concrete" (0.93) }

  LLM 2 (broad scope — full HomeInsurance + UserInfo + Address schemas):
    target: ALL fields across ALL entities
    result: { property_type: "apartment" (0.72), address: "88 Nanjing Rd" (0.68),
              first_name: null (0.0), last_name: null (0.0),
              phone: "138-1234-5678" (0.85), ← caught from full domain scan
              email: null (0.0) }

  --- MERGE & RESOLVE ---
  property_type:  LLM1(0.94) ≥ LLM2(0.72) → use LLM1 → "apartment"
  address:        LLM1(0.91) ≥ LLM2(0.68) → use LLM1 → "88 Nanjing Rd Shanghai 200001"
  building_age:   LLM1(0.87), LLM2(null)  → use LLM1 → "9"
  floor_area:     LLM1(0.96), LLM2(null)  → use LLM1 → "95"
  construction_material: LLM1(0.93), LLM2(null) → use LLM1 → "concrete"
  phone:          LLM1(null), LLM2(0.85)  → LLM2 only → CONFIRM with user later

  --- VALIDATE + TRANSFORM ---
  [Validate] all 5 narrow-scope fields → PASS
  [Transform] building_age: "9" → cast:int → 9 (building built 2015, current year 2024 → age=9)
     phone: not in current state scope → skip for now (will confirm later)

  --- AgentState update ---
  fieldExtractedList: ["property_type", "address", "building_age",
                       "floor_area", "construction_material"]
  collected_fields: {
    "PropertyInfo": { property_type: "apartment", address: "88 Nanjing Rd Shanghai 200001",
                      building_age: 9, floor_area: 95, construction_material: "concrete" }
  }
  NOTE: phone NOT in fieldExtractedList — it's a candidate from LLM 2,
        pending user confirmation. It is NOT in collected_fields.

  --- RESPONSE (Layer 3) ---
  "Great, I've captured your property details:
   ✅ Property type: apartment
   ✅ Address: 88 Nanjing Road, Shanghai 200001
   ✅ Building age: 9 years
   ✅ Floor area: 95 sqm
   ✅ Construction: concrete
   ⏳ Phone number: 138-1234-5678 — I'll confirm this in a moment.

   Let me verify your address..."

  [LLM + tool: lookup_property_record("88 Nanjing Road, Shanghai")]
  Internal: Property record verified. Flood zone: low. Crime rate: low.
  → guard passed: all PropertyInfo required fields non-null → enter collect_coverage_needs

-- collect_coverage_needs ----------------------------------------
  [LLM → stream]
  "Great, your apartment is 95 sqm in a concrete building from 2015.
   By the way, I noticed you mentioned your phone is 138-1234-5678 earlier.
   Is that your phone number?"  ← LLM 2 field confirmation

User:   "Yes, that's my phone. Both building and contents coverage.
         Building 2,000,000 CNY, contents 500,000 CNY.
         Standard deductible is fine. Add fire and theft riders."

  --- EXTRACTION (parallel) ---
  LLM 1 (narrow): { coverage_type: "both" (0.95), building_coverage: "2000000" (0.92),
                    contents_coverage: "500000" (0.88), deductible: "standard" (0.90),
                    riders: ["fire","theft"] (0.91) }
  LLM 2 (broad):  { coverage_type: "both" (0.78), phone: "13812345678" (0.91) }

  --- MERGE ---
  phone: LLM1(null), LLM2(0.91) → use LLM2 (user confirmed above)

  --- VALIDATE + TRANSFORM ---
  [Validate] coverage fields → PASS
  [Transform] phone: pattern "^138[0-9]{8}$" → PASS → "13812345678"

  --- AgentState update ---
  fieldExtractedList: [..., "coverage_type", "building_coverage",
                       "contents_coverage", "deductible", "riders", "phone"]
  collected_fields: {
    "PropertyInfo": { ... },
    "CoverageInfo": { coverage_type: "both", building_coverage: 2000000,
                      contents_coverage: 500000, deductible: "standard",
                      riders: ["fire","theft"] },
    "UserInfo": { phone: "13812345678" }     ← now in DomainModel
  }

  --- RESPONSE (Layer 3) ---
  "Got it! Here's what I've updated:
   ✅ Coverage type: both (building + contents)
   ✅ Building coverage: 2,000,000 CNY
   ✅ Contents coverage: 500,000 CNY
   ✅ Deductible: standard
   ✅ Riders: fire, theft
   ✅ Phone: 13812345678 — confirmed

   Let me assess your risk now..."

  → guard passed → enter assess_risk

-- assess_risk ---------------------------------------------------
  [code] compute_risk_score(age=11, material=concrete, flood_zone=low, crime_rate=low)
  → risk_score = 18 (low risk)
  → risk_factors = ["concrete_structure", "low_flood_zone", "low_crime"]
  → rate_multiplier = 0.8 + (18/250) = 0.872

  exit_guard: risk_score(18) < 70 → passed → enter calculate_premium

-- calculate_premium ---------------------------------------------
  [code] compute_home_premium:
    base_rate = 3.5 CNY per 1000 CNY coverage
    annual_premium = 3.5 * 0.872 * 2000000 / 1000 = 6,104 CNY
    monthly_premium = 508.67 CNY
    discount_applied = 0 (first year, no loyalty discount)

  exit_guard: annual_premium(6104) < 50000 → passed → enter present_quote

-- present_quote -------------------------------------------------
  [LLM → generate]
  "Here's your home insurance quote:

   Property: Apartment at 88 Nanjing Road, Shanghai 200001
   Coverage: Building 2,000,000 CNY + Contents 500,000 CNY
   Annual Premium: 6,104 CNY (508.67 CNY/month)
   Deductible: Standard (2,000 CNY)
   Riders: Fire, Theft

   Would you like to purchase this policy?"

  *** trigger interrupt(): paused, awaiting human approval ***

  --- audit: 2026-06-16 10:15:30 | present_quote | waiting_human ---

  Reviewer reviews quote → [Approve]

  --- audit: 2026-06-16 10:16:12 | present_quote | approved_by: agent_wang ---

User:   "Yes, I'll purchase it"

-- confirm_purchase ----------------------------------------------
  [code] create_home_policy()
  → policy_id: "HOM-2026-00142"
  → policy_status: active

  [LLM → stream]
  "Purchase confirmed! Your home insurance policy HOM-2026-00142 is active.
   Coverage effective immediately. You'll receive the policy document via email."

  → enter done

-- done ----------------------------------------------------------
  [code] log_conversation() → audit trail archived
```

### Key Design Points

| Feature | How Demonstrated |
|---------|-----------------|
| Parallel two-LLM extraction | LLM 1 (narrow scope) + LLM 2 (full schema) run concurrently each turn; merged by confidence matrix |
| LLM 2 broad scan catches out-of-order fields | User mentions phone in `collect_property_info`; LLM 2 catches it; confirmed in next state |
| Merge & confidence resolution | phone: LLM1(0.76 < 0.7) → fallback to LLM2(0.82 > 0.7) → use LLM2 value |
| fieldExtractedList tracking | Only fields passing Extract→Validate→Transform appear in fieldExtractedList |
| DomainModel = only verified data | phone fails Transform → NOT in collected_fields; UserInfo entity is partial but correct |
| LLM info collection | `collect_property_info`, `collect_coverage_needs` — conversational data gathering |
| Tool calling | `lookup_property_record` called by LLM to verify address |
| Deterministic business logic | `assess_risk`, `calculate_premium` — pure code, no LLM |
| Guard-based routing | `exit_guard: risk_score < 70` prevents high-risk auto-approval |
| Human-in-the-loop | `present_quote` triggers interrupt for compliance review |
| Guard meta-variables | `context_incomplete`, `exit_guard_pass` auto-managed by framework |

### Audit Log (Quote Path)

```json
[
  {"ts":"10:15:00","state":"collect_property_info", "action":"llm_extract_narrow","tokens":85,
   "target":"PropertyInfo fields","result":"property_type=apartment(0.94),address=...(0.91),building_age=9(0.87),floor_area=95(0.96),construction_material=concrete(0.93)"},
  {"ts":"10:15:00","state":"collect_property_info", "action":"llm_extract_broad","tokens":210,
   "target":"ALL schemas","result":"property_type=apartment(0.72),address=...(0.68),phone=138-1234-5678(0.85)"},
  {"ts":"10:15:00","state":"collect_property_info", "action":"extract_merge","result":"5 fields from narrow + 1 candidate(phone) from broad"},
  {"ts":"10:15:01","state":"collect_property_info", "action":"validate","result":"5/5 passed","fieldExtractedList":["property_type","address","building_age","floor_area","construction_material"]},
  {"ts":"10:15:01","state":"collect_property_info", "action":"transform","result":"building_age cast 9→9(int)","phone: deferred for next state"},
  {"ts":"10:15:02","state":"collect_property_info", "action":"tool_call","tool":"lookup_property_record","args":{"address":"88 Nanjing Road, Shanghai"},"result":{"flood_zone":"low","crime_rate":"low"}},
  {"ts":"10:15:02","state":"collect_property_info", "action":"transition","from":"collect_property_info","to":"collect_coverage_needs","guard":"all_required_fields_non_null","result":"passed"},
  {"ts":"10:15:08","state":"collect_coverage_needs", "action":"llm_extract_narrow","tokens":72,"result":"coverage_type=both(0.95),building_coverage=2000000(0.92),contents_coverage=500000(0.88),deductible=standard(0.90),riders=[fire,theft](0.91)"},
  {"ts":"10:15:08","state":"collect_coverage_needs", "action":"llm_extract_broad","tokens":198,"result":"coverage_type=both(0.78),phone=13812345678(0.91)"},
  {"ts":"10:15:08","state":"collect_coverage_needs", "action":"extract_merge","result":"phone: LLM2(0.91), user confirmed above → merged; fieldExtractedList+=[...,phone]"},
  {"ts":"10:15:09","state":"collect_coverage_needs", "action":"transform","result":"phone: pattern pass, normalize → 13812345678"},
  {"ts":"10:15:09","state":"collect_coverage_needs", "action":"transition","from":"collect_coverage_needs","to":"assess_risk","guard":"building_coverage>0","result":"passed"},
  {"ts":"10:15:10","state":"assess_risk",           "action":"code_exec","fn":"compute_risk_score","input":{"age":9,"material":"concrete"},"result":{"risk_score":14,"rate_multiplier":0.856}},
  {"ts":"10:15:10","state":"assess_risk",           "action":"transition","from":"assess_risk","to":"calculate_premium","guard":"exit_guard_pass","result":"passed"},
  {"ts":"10:15:10","state":"calculate_premium",     "action":"code_exec","fn":"compute_home_premium","result":{"annual_premium":5992,"monthly_premium":499.33}},
  {"ts":"10:15:10","state":"calculate_premium",     "action":"transition","from":"calculate_premium","to":"present_quote","guard":"annual_premium<50000","result":"passed"},
  {"ts":"10:15:30","state":"present_quote",         "action":"interrupt","reason":"human_review"},
  {"ts":"10:16:12","state":"present_quote",         "action":"approved","approver":"agent_wang"},
  {"ts":"10:16:15","state":"present_quote",         "action":"transition","from":"present_quote","to":"confirm_purchase","guard":"user_says_yes","result":"passed"},
  {"ts":"10:16:15","state":"confirm_purchase",      "action":"code_exec","fn":"create_home_policy","result":{"policy_id":"HOM-2026-00142","status":"active"}},
  {"ts":"10:16:15","state":"done",                  "action":"complete"}
]
```

---

## Scenario 2: File & Settle Claim

### Dialogue Flow

```
User:   "There was a fire in my kitchen last night, I need to file a claim"

-- file_claim ----------------------------------------------------
  [LLM → stream]
  "I'm sorry to hear that. I'll help you file a claim right away.
   First, can you tell me:
   - When exactly did the incident happen?
   - Can you describe the damage?
   - What's your estimated loss amount?
   - Do you have any photos you can upload?"

User:   "It happened yesterday evening around 8pm, June 10th.
         Kitchen cabinets and appliances damaged by fire and smoke.
         I estimate about 80,000 CNY in damage.
         Here are the photos." [uploads 3 images]

  [LLM + tool: upload_attachment(img1,img2,img3)]
  [LLM + tool: lookup_policy(user_id) → policy_id=HOM-2026-00142, status=active]

  output:
    incident_type = "fire"
    incident_date = "2026-06-10"
    damage_description = "Kitchen cabinets and appliances damaged by fire/smoke"
    estimated_loss = 80000
    attachments = ["img_001.jpg", "img_002.jpg", "img_003.jpg"]

  → guard passed → enter validate_claim

-- validate_claim ------------------------------------------------
  [code] run_claim_validations:
    Step 1: check_policy_active("HOM-2026-00142") → active ✓
    Step 2: check_incident_covered("fire") → fire is covered ✓
    Step 3: check_incident_in_period("2026-06-10", policy_start) → within coverage ✓
    Step 4: check_duplicate_claim("fire", "2026-06-10") → no duplicate ✓
  validation_passed: true
  coverage_limit: 2000000  (building coverage)

  exit_guard: validation_passed → enter assess_damage

-- assess_damage -------------------------------------------------
  [LLM + tool: estimate_repair_cost(kitchen_fire, photos=[...])]
  → adjuster_report: {
      damage_type: "fire_smoke",
      affected_areas: ["kitchen_cabinets", "countertops", "appliances", "wall_repaint"],
      repair_estimate: 75000,
      replacement_estimate: 85000,
      recommended: "repair"
    }

  assessed_amount = 75000
  deductible = 2000 (standard)
  covered_amount = min(75000 - 2000, 2000000) = 73000

  exit_guard: assessed_amount(75000) > 0 → enter approve_claim

-- approve_claim -------------------------------------------------
  [LLM → generate]
  "Claim assessment complete:

   Incident: Kitchen fire on 2026-06-10
   Assessed Damage: 75,000 CNY
   Deductible: 2,000 CNY
   Covered Amount: 73,000 CNY
   Coverage Limit: 2,000,000 CNY

   Your claim is ready for approval."

  *** trigger interrupt(): paused, awaiting human approval ***

  --- audit: 2026-06-11 09:30:45 | approve_claim | waiting_human ---

  Claims adjuster reviews → [Approve]

  --- audit: 2026-06-11 09:45:00 | approve_claim | approved_by: adjuster_li ---

-- process_claim_payment -----------------------------------------
  [code] execute_claim_payout:
    idempotency_key = "idem_claim_HOM-2026-00142_fire_20260610"
    POST /payouts {policy_id: "HOM-2026-00142", amount: 73000, key: "idem_..."}
    → payout_id: "PAY-2026-00842"
    → payout_status: "completed"

  postcondition: payout_id="PAY-2026-00842" passed

  [LLM → stream]
  "Claim approved and payout processed! 73,000 CNY has been transferred
   to your registered account. Payout reference: PAY-2026-00842.
   You'll receive a detailed settlement letter by email."

  → enter done

-- done ----------------------------------------------------------
  [code] log_conversation() → audit trail archived
```

### Key Design Points

| Feature | How Demonstrated |
|---------|-----------------|
| Intent-based entry routing | `intent=file_claim` enters claim branch from `start` |
| Tool-augmented LLM | `upload_attachment`, `estimate_repair_cost` called during LLM states |
| Multi-step deterministic validation | `validate_claim` runs 4 checks as pure code |
| Deductible + coverage limit math | `assess_damage` computes `covered_amount = assessed - deductible`, capped at limit |
| Idempotent payout | `process_claim_payment` uses `idempotency_key` to prevent duplicate transfers |
| Error recovery path | `on_error: claim_error_recovery` catches payment gateway failures |

---

## Scenario 3: High Risk → Manual Review → Rejection

```
User:   "I want a quote for my wooden villa in a flood zone"

-- collect_property_info -----------------------------------------
  → property_type=villa, building_age=45, construction_material=wood_frame
  → flood_zone detected via lookup_property_record: "high"

-- collect_coverage_needs ----------------------------------------
  → coverage_type=both, building_coverage=5000000, deductible=standard

-- assess_risk ---------------------------------------------------
  [code] compute_risk_score(age=45, material=wood_frame, flood_zone=high)
  → risk_score = 91 (very high risk)
  → risk_factors = ["wood_frame_structure", "building_age_45", "high_flood_zone"]
  → rate_multiplier = 1.164

  exit_guard: risk_score(91) < 70 → FAILED
  exit_guard_blocked → routed to high_risk_review (NOT calculate_premium)

-- high_risk_review ----------------------------------------------
  *** trigger interrupt(): entered underwriter review queue ***

  Underwriter reviews → [Reject]
  Reason: "Flood zone high, wood frame — risk exceeds underwriting guidelines"

  guard: manual_review_rejected → enter done
  → Workflow ends without quote
```

This scenario demonstrates **guard-based alternate routing**: the `exit_guard` on `assess_risk` actively blocks the normal path and redirects to manual review, where a human makes the final decision.

---

## Scenario 4: Partial Extraction Failure — Phone Transform Fails

**DomainModel invariant in action:** phone passes Extract and Validate but fails Transform
(format mismatch). phone is NOT added to `collected_fields` — the UserInfo entity
only contains verified data.

```
-- collect_policyholder_info -------------------------------------

User:   "My name is Bob Smith, email bob@example.com,
         phone is 555-1234"

  --- EXTRACTION (parallel) ---
  LLM 1 (narrow): { first_name: "Bob" (0.88), last_name: "Smith" (0.91),
                    email: "bob@example.com" (0.94),
                    phone: "555-1234" (0.76) }   ← low confidence
  LLM 2 (broad):  { first_name: "Bob" (0.82), last_name: "Smith" (0.85),
                    phone: "5551234" (0.82) }

  --- MERGE ---
  first_name: LLM1(0.88) ≥ LLM2(0.82) → use LLM1 → "Bob"
  last_name:  LLM1(0.91) ≥ LLM2(0.85) → use LLM1 → "Smith"
  email:      LLM1(0.94), LLM2(null)  → use LLM1 → "bob@example.com"
  phone:      LLM1(0.76) < 0.7, LLM2(0.82) > 0.7 → use LLM2 → "5551234"

  --- VALIDATE ---
  first_name: type=string, minLength=1 → PASS
  last_name:  type=string, minLength=1 → PASS
  email:      type=string, format=email → PASS
  phone:      type=string, pattern="^\\+?1?\\d{10}$" → PASS (10 digits)

  --- TRANSFORM ---
  first_name: op=trim → PASS → "Bob"
  last_name:  op=trim → PASS → "Smith"
  email:      op=trim → PASS → "bob@example.com"
  phone:      op=normalize(to:+1NXXNXXXXXX) → FAIL
               "5551234" → cannot format to +1 (missing area code)
               → Transform FAILED

  --- AgentState update ---
  fieldExtractedList: ["first_name", "last_name", "email"]
  collected_fields: {
    "UserInfo": { first_name: "Bob", last_name: "Smith", email: "bob@example.com" }
  }
  NOTE: phone NOT in fieldExtractedList — Transform failed.
        phone NOT in collected_fields — UserInfo entity is PARTIAL but CORRECT.
        context_complete guard for UserInfo checks required: [first_name, last_name, email]
        → all three present → guard passes → state advances

  The bot does NOT ask about phone again in this state (it's optional in UserInfo).
  If phone were required, the context_incomplete guard would keep the user in
  this state and ask for a valid phone number.

  --- RESPONSE (Layer 3) ---
  "Thanks, Bob! Here's what I've captured:
   ✅ First name: Bob
   ✅ Last name: Smith
   ✅ Email: bob@example.com
   ❌ Phone: 555-1234 — couldn't validate (missing area code).
        Can you provide a full number with area code, e.g., +1-416-555-1234?"

  NOTE: The response explicitly tells the user which fields succeeded (✅)
        and which failed (❌) with a reason. The failed field is re-requested
        with format guidance. The DomainModel already contains the 3 valid fields.
```

---

## Cross-Reference

| Concept | Quote Path | Claim Path |
|---------|-----------|------------|
| Parallel two-LLM extraction | `collect_property_info` (LLM1 narrow + LLM2 broad) | — |
| Confidence-based merge | phone: LLM1(0.76) → LLM2(0.82) | — |
| fieldExtractedList tracking | 5 fields passed → list updated | — |
| DomainModel = only verified data | phone fails Transform → NOT in collected_fields | — |
| Response: success/failure report | ✅ address / ❌ phone with reason | — |
| LLM data collection | `collect_property_info` | `file_claim` |
| Deterministic validation | `assess_risk` | `validate_claim` |
| LLM assessment | — | `assess_damage` |
| Human review | `present_quote` | `approve_claim` |
| Irreversible operation | `confirm_purchase` | `process_claim_payment` |
| Error recovery | `error_recovery` | `claim_error_recovery` |
| Guard routing | `exit_guard: risk_score < 70` | `exit_guard: validation_passed` |
