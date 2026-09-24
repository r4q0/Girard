# Model comparison (Nebius Token Factory)

Every chat model on Nebius ran the same 8-line sales call (Koref as the seller) with the same draft advice prompt, plus one call-memory task. Times are measured from this laptop, one request at a time, after one warm-up request. Pick one **fast model** for live advice (speed matters most) and one **big model** for call memory and the debrief (quality matters most).

- **First word**: time until the first visible word of advice (median / slowest).
- **Full advice**: time until the whole answer is done (median).
- **Valid**: answers that were proper JSON with bullets, out of 8.
- **$ per 1,000 advice**: estimated at list price (cached prompt tokens are cheaper, so real cost is lower).
- **Memory**: time for the call-memory task, and whether its JSON was valid.

## My read

- **Fast model (live advice): GLM-5.2.** Best advice of the fast group: reuses the prospect's words and numbers, asks sharp questions, noticed the repeated hourly-rate question ("They keep asking hourly, explain once more"). Full advice in ~0.8 s.
- **Runner-up: gpt-oss-120b.** Fastest reliable model (~0.5 s full advice), solid but more generic.
- **Avoid for advice:** MiniCPM-V-4.5 and Nemotron-3-Nano are fast but invent facts ("Exact integration is standard for us", "your hourly rate is EUR 150"); Qwen3-30B (the old model) invents numbers ("~15 hours/week").
- **Big model (call memory + debrief): GLM-5.2 or Kimi-K3.** Both produced the most complete call memory (all three companies, all open objections). Kimi-K2.6 and Qwen3.5 wrongly recorded "40 cents per document" as the prospect's budget.
- Thinking models only work here with thinking switched off; the table uses the right switch per model.

| Model | First word (ms) | Full advice (ms) | Valid | $ per 1,000 advice | Memory (s) |
| --- | --- | --- | --- | --- | --- |
| openbmb/MiniCPM-V-4_5 | 168 / 187 | 416 | 8/8 | 1.13 | 0.8 |
| openai/gpt-oss-120b | 306 / 456 | 471 | 8/8 | 0.30 | 2.6 |
| nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B | 252 / 266 | 595 | 8/8 | 0.12 | 0.8 |
| zai-org/GLM-5.2 | 420 / 478 | 825 | 8/8 | 2.57 | 1.1 |
| nvidia/Nemotron-3-Ultra-550b-a55b | 757 / 832 | 995 | 8/8 | 1.93 | 0.9 |
| moonshotai/Kimi-K2.6 | 687 / 778 | 1053 | 8/8 | 1.81 | 0.9 |
| NousResearch/Hermes-4-405B | 194 / 225 | 1137 | 8/8 | 1.74 | 2.6 |
| Qwen/Qwen3.5-397B-A17B | 743 / 981 | 1147 | 8/8 | 1.28 | 1.9 |
| deepseek-ai/DeepSeek-V4-Pro-0813 | 829 / 943 | 1179 | 8/8 | 2.49 | 1.2 |
| deepseek-ai/DeepSeek-V4-Pro | 603 / 689 | 1204 | 8/8 | 3.09 | 1.6 |
| Qwen/Qwen3-30B-A3B-Instruct-2507 | 192 / 261 | 1235 | 8/8 | 0.18 | 2.1 |
| moonshotai/Kimi-K3 | 675 / 1022 | 1284 | 8/8 | 5.83 | 1.7 |
| google/gemma-3-27b-it | 241 / 367 | 1356 | 8/8 | 0.20 | 1.4 |
| deepseek-ai/DeepSeek-V4-Flash-0731 | 816 / 2309 | 1567 | 8/8 | 0.25 | 1.5 |
| zai-org/GLM-5.3 | 776 / 1148 | 1597 | 8/8 | 2.56 | 1.8 |
| deepseek-ai/DeepSeek-V4.1-Flash | 853 / 1021 | 1789 | 8/8 | 0.58 | 3.1 |
| zai-org/GLM-5.3-Flash | 922 / 1380 | 1903 | 8/8 | 0.27 | 2.2 |
| Qwen/Qwen3-235B-A22B-Instruct-2507 | 580 / 1664 | 2228 | 8/8 | 0.36 | 1.8 |
| nvidia/Nemotron-3_5-Lightning | 205 / 220 | 367 | 7/8 | 0.11 | 0.6 |
| nvidia/nemotron-3-super-120b-a12b | 713 / 809 | 1058 | 7/8 | 0.65 | 1.1 |
| zai-org/GLM-5.1 | 237 / 299 | 1380 | 1/8 | 2.45 | 3.8 |
| MiniMaxAI/MiniMax-M3 | 2583 / 3813 | 2730 | 6/8 | 1.42 | 2.3 |
| moonshotai/Kimi-K2.7-Code | 3986 / 4370 | 4172 | 2/8 | 4.93 | 7.1 (invalid) |

## What each model actually said

Read these to judge quality: specific to what the prospect said, short, no invented facts (Koref has no case studies).

<details><summary><b>openbmb/MiniCPM-V-4_5</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- We can fix this with a workflow assessment for EUR 500.
- The report will show cost per process and fixed quote per automation.

**Prospect:** What's your hourly rate?  
- We don't bill by the hour; fixed price, scope and date agreed before any code.

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Koref's fixed price covers all work, unlike Flowbase's per-document cost.
- Exact integration is standard for us, not an extra cost.
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Koref's 18-month payback guarantee covers budget overruns.
- We fix scope and date before coding, so no surprises.

**Prospect:** Is our data going to leave the Netherlands?  
- Koref hosts data in the Netherlands, on open-source models, with mutual NDA.
- No outside AI provider sees your documents.

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Koref's software connects systems directly, not via Zapier, for reliability.

**Prospect:** I'd need to discuss this with my co-owner first.  
- We can schedule a 30-min discovery call with your co-owner.
- This will help us understand their needs and discuss the workflow assessment.

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We don't use hourly rates; fixed price, scope, and date agreed before start.
- Our 18-month payback guarantee means the build pays for itself or we pay back the difference.

**Call memory:**

```json
{
 "budget": "went way over budget with last IT company",
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "typing orders from email into Exact",
  "Zapier keeps breaking",
  "data leaving Netherlands"
 ],
 "objections": [
  {
   "topic": "hourly rate",
   "status": "open"
  },
  {
   "topic": "data leaving Netherlands",
   "status": "open"
  }
 ],
 "companies": [
  "Flowbase"
 ],
 "timeline": "need to discuss with co-owner"
}
```

</details>

<details><summary><b>openai/gpt-oss-120b</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Ask: "How many minutes per person each morning for typing orders?"
- Highlight: automation can replace that manual entry with a fixed‑price build.
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- Explain we work on fixed price, not hourly; start with a €500 assessment.
- "Would a fixed‑price quote after the assessment address your budgeting concerns?"

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Emphasize Koref’s fixed‑price, pay‑back guarantee versus Flowbase’s €0.40 per document.
- "Would a fixed quote that eliminates per‑document fees be more appealing for you?"
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Highlight our fixed‑price, scope‑and‑date contract eliminates budget overruns.
- Mention the 18‑month payback guarantee protects their investment.
- "Would a guaranteed no‑overrun quote ease your concerns?"

**Prospect:** Is our data going to leave the Netherlands?  
- Reassure: all processing runs on Dutch‑hosted, open‑source models; data never leaves NL
- _research:_ Flowbase

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Highlight Koref’s fixed‑price automation that replaces unreliable Zapier flows.
- Reassure: all processing stays Dutch‑hosted, no data leaves the Netherlands.

**Prospect:** I'd need to discuss this with my co-owner first.  
- Suggest a brief joint call: "When can we include your co‑owner to review the fixed‑price proposal?"

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- Explain we never bill hourly; we give a fixed price after assessment.
- "Does a fixed‑price quote with an 18‑month payback guarantee address your budgeting concerns?"

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "manual typing of orders from email",
  "Zapier frequently breaks",
  "concern about data leaving the Netherlands",
  "previous IT project went over budget"
 ],
 "objections": [
  {
   "topic": "hourly rate / pricing clarity",
   "status": "open"
  }
 ],
 "companies": [
  "Flowbase"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Exact integration can automate those three email orders daily
- Automation build pays for itself within 18 months, guaranteed
- Would you like to see a quick workflow assessment?
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We work on fixed price, not hourly rates.
- Our 18-month payback guarantee covers the build cost.
- Would you like to see a fixed quote for automating those three email orders?
- _research:_ Exact

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Your hourly rate is EUR 150, but we fix price and guarantee payback in 18 months.
- Flowbase's forty cents per document adds up; we automate the whole email‑to‑Exact flow for a fixed fee.
- Would you like to see a fixed‑price quote that eliminates hourly billing?
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Your team spends three people typing orders into Exact every morning.
- We offer a fixed-price automation with an 18-month payback guarantee.
- Flowbase charges forty cents per document; we can match or beat that with a fixed scope.
- _research:_ Exact

**Prospect:** Is our data going to leave the Netherlands?  
- Your data stays in the Netherlands; we use Dutch‑hosted open‑source models.
- We can show you a fixed‑price automation that eliminates the three manual email‑to‑Exact steps.
- Would you like to see how the 18‑month payback guarantee works for your order process?
- _research:_ Koref

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Your three people type orders into Exact every morning, right?
- Zapier breaks; we can automate that task with a fixed‑price build.
- Your data stays in the Netherlands; we host it locally.
- _research:_ Exact

**Prospect:** I'd need to discuss this with my co-owner first.  
- Your three people type orders into Exact daily, costing roughly EUR 48 per hour each.
- We fix that with a fixed-price automation, paying for itself within 18 months.
- Is our data staying in the Netherlands?
- _research:_ Koref

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We charge a fixed price per automation, not hourly, so costs stay predictable.
- Your data stays in the Netherlands; we use Dutch‑hosted open‑source models.
- We guarantee the build pays for itself within 18 months or we refund the difference.
- _research:_ Koref

**Call memory:**

```json
{
 "budget": "forty cents per document",
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "typing incoming orders from email into Exact",
  "Zapier keeps breaking"
 ],
 "objections": [
  {
   "topic": "hourly rate",
   "status": "open"
  },
  {
   "topic": "data leaving the Netherlands",
   "status": "open"
  }
 ],
 "companies": [
  "Flowbase"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>zai-org/GLM-5.2</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Three people, most of their morning, that's exactly the kind of manual bridge we fix.
- Quick check: roughly how many orders per day, and how many minutes each?
- If it's over ~EUR 10,000/year in time, a fixed-price build likely meets the payback guarantee.
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We work fixed price, not hourly, scope and date agreed before any code.
- With 3 people typing orders into Exact daily, that's likely over €10k/year in manual effort.
- "How many orders per morning, and how many minutes each takes your team?"

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- At 40 cents per document you pay forever; Koref gives fixed price, scope, and date upfront.
- With Flowbase you keep paying per doc; Koref's build pays for itself in 18 months or we pay back the difference.
- "How many order documents per day do those three people handle?"
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- That's exactly why we work fixed price, scope, and date, overruns are our cost.
- Mention the 18-month payback guarantee: if it doesn't save enough, we pay back the difference.
- Ask how much the over-budget project cost them to frame the comparison.

**Prospect:** Is our data going to leave the Netherlands?  
- No, open-source models, Dutch-hosted, on infrastructure Koref or you control.
- Contrast: with Flowbase you depend on their provider's data policy; Koref gives you certainty.
- Ask: "Would Dutch hosting address a concern your co-owner has about data?"
- _research:_ Flowbase

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaking is exactly the 'two systems not talking' problem we fix permanently.
- We connect email and Exact directly, fixed price, no per-document cost.
- Ask: 'How often does Zapier break, and what happens to those orders when it does?'
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Acknowledge the co-owner decision, no pressure, just next steps.
- Offer the EUR 500 workflow assessment as a concrete take-away: report within 2 days, theirs to keep.
- Ask: 'Would it help if I sent a one-page summary your co-owner can review?'

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- They keep asking hourly, explain fixed price one more time, plainly.
- We don't bill hours. You get a fixed price, scope, and date before any code.
- Ask: "What if I told you the price is fixed and overruns are on us?"

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "Three people spend most of morning typing orders from email into Exact",
  "Zapier keeps breaking for some of the process",
  "Last IT company went way over budget"
 ],
 "objections": [
  {
   "topic": "hourly rate / pricing model unclear",
   "status": "open"
  },
  {
   "topic": "data leaving the Netherlands",
   "status": "open"
  },
  {
   "topic": "past IT vendor went over budget",
   "status": "open"
  }
 ],
 "companies": [
  "Exact",
  "Flowbase",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>nvidia/Nemotron-3-Ultra-550b-a55b</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Three people typing email orders into Exact every morning is the exact waste we automate.
- Workflow assessment (EUR 500 fixed) measures the yearly cost and gives a fixed build quote with 18-month payback guarantee.
- "What is the co-owner's main concern about a fixed-price approach?"
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We don't bill hourly; fixed price, scope and date agreed upfront.
- Delays are our cost, not yours; 18-month payback guarantee.
- "What does the current manual entry cost you per year?"

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Flowbase charges per document; Koref fixes price, scope and date before any code.
- Your 3 people typing orders into Exact is the baseline we measure savings against.
- "What volume of orders per day are we talking about?"
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Fixed price, scope and date agreed before any code; delays are Koref's cost
- 18-month payback guarantee: the build pays for itself within 18 months or Koref pays back the difference
- Client owns the code, documentation and data; no lock-in

**Prospect:** Is our data going to leave the Netherlands?  
- Data stays in NL on Dutch-hosted open models; no outside provider sees it
- Mutual NDA before assessment; data processing agreement before build
- "Where is Exact hosted today?"

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaks because it's not built for Exact's API limits.
- We build a fixed-price connector that handles retries and logging.
- "What does one broken Zapier run cost you in manual cleanup time?"
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Offer a free 30-min discovery call with both owners
- Send the EUR 500 assessment report they keep regardless
- "What would your co-owner need to see to feel comfortable?"

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We don't bill hours; fixed price, scope and date agreed before any code
- Assessment is EUR 500 fixed; gives you a fixed quote per automation with 18-month payback guarantee
- "What would a fixed price need to include for you to compare it to Flowbase's per-document cost?"
- _research:_ Flowbase

**Call memory:**

```json
{
 "budget": "Flowbase quoted forty cents per document",
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "three people spend mornings typing orders into Exact",
  "Zapier keeps breaking",
  "last IT company went way over budget"
 ],
 "objections": [
  {
   "topic": "pricing model unclear",
   "status": "open"
  },
  {
   "topic": "data residency Netherlands",
   "status": "open"
  }
 ],
 "companies": [
  "Exact",
  "Flowbase",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>moonshotai/Kimi-K2.6</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Three people typing email orders into Exact every morning, likely EUR 15,000+/yr in loaded cost.
- Our workflow assessment maps exact savings and gives a fixed build quote.
- "What happens to orders when one of those three people is sick or on holiday?"
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We don't work hourly. Fixed price, scope and date before any code.
- Delays are our cost, not yours. Payback guarantee covers the build.
- "Shall I explain how the EUR 500 workflow assessment gives a fixed quote?"

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Ask: 'Is that forty cents forever, or does volume change the price?'
- Flowbase charges per document; Koref fixes price before any code.
- With 3 staff mornings lost, likely payback in months, not years.
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Fixed price, scope and date before any code; overruns are Koref's cost.
- 18-month payback guarantee: if it doesn't pay for itself, we pay back the difference.
- Ask: "What does 'way over budget' mean in euros, so I can show how we prevent that?"

**Prospect:** Is our data going to leave the Netherlands?  
- Dutch-hosted, open-source models; no outside AI provider sees your documents.
- Mutual NDA before assessment, data processing agreement before any build.
- You own the code and data; take it in-house or move after 12 months.

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaks because it's generic glue, not owned code. Koref builds yours, documented, with liability after go-live.
- Flowbase's forty cents adds up and can change. Koref is fixed price, scope and date before any code.
- "Shall I walk through how the 18-month payback guarantee works with a fixed quote?"
- _research:_ Flowbase

**Prospect:** I'd need to discuss this with my co-owner first.  
- Offer the EUR 500 assessment: fixed price, report in 2 days, co-owner sees exact payback.
- Mention the 18-month guarantee directly answers their budget-overrun worry.
- Ask: 'Shall I send the assessment terms so your co-owner can review before we book a call?'

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We don't use hourly rates; fixed price, scope and date before any code.
- Delays are our cost, not yours. No budget overruns like your last IT company.
- "Shall I walk through the EUR 500 workflow assessment that produces the fixed quote?"

**Call memory:**

```json
{
 "budget": "forty cents per document",
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "three people typing orders from email into Exact",
  "Zapier keeps breaking",
  "last IT company went way over budget"
 ],
 "objections": [
  {
   "topic": "data leaving Netherlands",
   "status": "open"
  },
  {
   "topic": "pricing model unclear",
   "status": "open"
  }
 ],
 "companies": [
  "Flowbase"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>NousResearch/Hermes-4-405B</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Ask: 'How many orders per day, roughly?'
- Ask: 'What is the loaded hourly cost for those staff?'
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We don't bill hourly. We agree a fixed price before any code.
- The price is based on the yearly cost of the task, which we calculate in the assessment.

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- We don't do hourly rates or per-document fees. Fixed price for the whole build.
- Flowbase is a good tool, but we connect to your systems and remove the whole task.
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- "We don't bill hourly. We agree a fixed price before any code."
- If it takes longer than agreed, that's our cost, not yours.

**Prospect:** Is our data going to leave the Netherlands?  
- Dutch-hosted, open-source models, on infrastructure you or we control
- Mutual NDA before assessment, data processing agreement before build

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Ask: 'What breaks most often with Zapier?'
- Note: Our fixed price includes fixing breaks after go-live

**Prospect:** I'd need to discuss this with my co-owner first.  
- Suggest: 'Let's get you the assessment report first, then you can discuss with your co-owner with all the numbers.'
- Offer: 'The assessment is fixed at EUR 500, no further obligation.'

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- "We don't have an hourly rate. We quote a fixed price for the whole project."
- The price is based on the yearly cost of the task, which we calculate in the assessment.

**Call memory:**

```json
{
 "budget": "last IT company went way over budget",
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "three people spend morning typing orders from email into Exact",
  "Zapier keeps breaking"
 ],
 "objections": [
  {
   "topic": "hourly rate",
   "status": "open"
  },
  {
   "topic": "data leaving Netherlands",
   "status": "open"
  },
  {
   "topic": "pricing confusion",
   "status": "open"
  }
 ],
 "companies": [
  "Exact",
  "Flowbase",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>Qwen/Qwen3.5-397B-A17B</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Quantify the cost: 3 people x minutes/order x EUR 48/hr x 230 days.
- Mention the EUR 500 assessment to measure this exact waste.
- "What if we fixed the Exact connection for a fixed price?"
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We do not charge hourly; we agree on a fixed price upfront.
- Delays are our cost, not yours, under our guarantee.
- Shall we focus on the 18-month payback for your Exact automation?

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Contrast their 40 cents per document variable cost with our fixed price.
- Ask: "Does Flowbase's quote include operational liability after go-live?"
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Contrast their past overrun with Koref's fixed price where delays are our cost.
- Ask: "Would a written guarantee that you pay zero extra if we overrun help?"

**Prospect:** Is our data going to leave the Netherlands?  
- Confirm data stays in the Netherlands on Dutch-hosted infrastructure.
- Remind them Koref takes operational liability, unlike their last IT partner.

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Fix the root cause: systems not talking, not just the connector.
- "Would a fixed price with a payback guarantee remove the budget risk?"
- Data stays Dutch-hosted; open-source models ensure no outside access.
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Suggest a quick three-way call to align both co-owners on the fixed-price guarantee.
- Remind them the EUR 500 assessment report is theirs to keep regardless of the build decision.
- _research:_ Flowbase

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We never charge hourly; we agree on a fixed price before any code.
- Delays are Koref's cost, not yours, avoiding past budget overruns.
- "Shall we start with the EUR 500 assessment to lock in a fixed quote?"
- _research:_ Flowbase

**Call memory:**

```json
{
 "budget": "40 cents per document",
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "Three people manually type orders into Exact.",
  "Zapier integration keeps breaking."
 ],
 "objections": [
  {
   "topic": "Previous IT company went over budget",
   "status": "open"
  },
  {
   "topic": "Data residency outside Netherlands",
   "status": "open"
  },
  {
   "topic": "Confusion about hourly rate pricing",
   "status": "open"
  }
 ],
 "companies": [
  "Exact",
  "Flowbase",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>deepseek-ai/DeepSeek-V4-Pro-0813</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- That's a clear automation case: email orders into Exact without manual typing.
- Ask: "How many orders per person each morning?"
- Mention fixed price and 18-month payback guarantee.
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We don't work hourly: fixed price, scope and date agreed before any code.
- You buy the outcome, not hours; delays are our cost, not yours.
- "Shall I show what a fixed quote for the Exact order entry would look like?"

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Flowbase charges per document; Koref fixes price and date before any code.
- Ask: "How many documents per month, so we can compare total yearly cost?"
- Your three people typing into Exact is a fixed task, not a per-document cost.
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Fixed price and date agreed before any code; overruns are Koref's cost.
- 18-month payback guarantee: if it doesn't pay for itself, Koref pays the difference.
- "What did the last project end up costing versus the original quote?"

**Prospect:** Is our data going to leave the Netherlands?  
- No: Dutch-hosted, open-source models, on infrastructure you or Koref controls.
- No outside AI provider sees your documents; mutual NDA before the assessment.
- Data processing agreement is signed before any build starts.

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaking is exactly the 'two systems not talking' problem we fix.
- A fixed-price build replaces the fragile Zapier setup with something reliable.
- "What does a Zapier break cost you in a week?"
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Offer to brief the co-owner directly on the fixed price and 18-month guarantee.
- Ask: "What would your co-owner need to see to move forward?"

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- No hourly rate: fixed price, scope and date agreed before any code.
- You pay the agreed amount; delays are our cost, not yours.
- "What would make the fixed price easier to compare with Flowbase?"
- _research:_ Flowbase

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "manual order entry into Exact",
  "Zapier keeps breaking",
  "previous IT company went over budget"
 ],
 "objections": [
  {
   "topic": "pricing",
   "status": "open"
  },
  {
   "topic": "data residency",
   "status": "open"
  }
 ],
 "companies": [
  "Flowbase"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>deepseek-ai/DeepSeek-V4-Pro</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- That Exact typing is a classic two-systems-not-talking fix.
- Our EUR 500 assessment measures the yearly cost and gives a fixed quote.
- "Would a fixed price and an 18-month payback guarantee make this worth a look?"
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We don't charge by the hour. We agree a fixed price, scope and date upfront.
- That means you buy the outcome, not our time. No overrun risk for you.

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Flowbase charges per document; we fix the price upfront so costs don't grow with volume.
- Our 18-month payback guarantee means the build pays for itself or we refund the difference.
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Fixed price and date agreed before code; overruns are Koref's cost, not yours.
- The 18-month payback guarantee means the build pays for itself or we refund the difference.
- _research:_ Flowbase

**Prospect:** Is our data going to leave the Netherlands?  
- All data stays Dutch-hosted, on open-source models we or you control.
- No outside AI provider ever sees your documents.
- Mutual NDA before assessment; data processing agreement before any build.

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaking means hidden cost: rework, delays, and Exact still not up to date.
- Our fixed-price build replaces fragile glue with reliable, documented software you own.
- "If we agree a fixed scope and date, would that remove the over-budget risk you felt last time?"
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Suggest a EUR 500 assessment: gives you both a fixed quote and payback numbers to decide together.
- Offer to join a 15-minute call with your co-owner to walk through the report.

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- No hourly rate. Fixed price, scope and date agreed before any code.
- You buy the outcome, not our time. Overrun risk stays with us.
- The assessment gives a fixed quote; EUR 500, report in 2 days.

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "typing incoming orders from email into Exact manually",
  "Zapier keeps breaking"
 ],
 "objections": [
  {
   "topic": "pricing model unclear",
   "status": "open"
  },
  {
   "topic": "data leaving the Netherlands",
   "status": "open"
  },
  {
   "topic": "previous IT company went over budget",
   "status": "open"
  }
 ],
 "companies": [
  "Flowbase",
  "Exact",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>Qwen/Qwen3-30B-A3B-Instruct-2507</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- 3 people typing orders into Exact every morning: that's a clear pain point
- We fix this with automation: no more manual entry, just one system
- Want a fixed-price quote for this? We can deliver in weeks
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We work with fixed prices, not hourly rates
- Your team spends ~15 hours/week on this task
- What’s your current cost for those 15 hours?

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Flowbase quote: ~$0.40 per document, but no fixed price or timeline
- We offer fixed price, scope, and date, no surprise costs
- What’s your current cost per document? We can compare directly
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Fixed price, scope, and date agreed before any code, no overruns
- 18-month payback guarantee: we cover the difference if it doesn’t pay for itself
- What was the budget range with the last IT company?
- _research:_ Flowbase

**Prospect:** Is our data going to leave the Netherlands?  
- Yes, your data stays in the Netherlands
- We use open-source models hosted where you choose
- No outside AI provider sees your documents

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaks because it's not built for your workflow, Koref fixes it permanently
- We use Dutch-hosted, open-source models, your data stays in the Netherlands
- What’s the cost per document with Zapier when it breaks and needs fixing?
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Co-owner needs to know: fixed price, no overruns, 18-month payback guarantee
- Ask: 'What would make this decision easier for your co-owner?'
- Mention: Dutch-hosted, open-source models, data stays in NL
- _research:_ Flowbase

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We don't use hourly rates, fixed price, scope, and date before any code
- Your 3 people typing orders: we quote based on that exact task
- Ask your co-owner: 'What’s the cost of 3 people doing this every day?'

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "Manual data entry in the morning",
  "Zapier keeps breaking",
  "Previous IT company over budget"
 ],
 "objections": [
  {
   "topic": "Pricing model",
   "status": "open"
  },
  {
   "topic": "Data leaving the Netherlands",
   "status": "open"
  }
 ],
 "companies": [
  "Flowbase"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>moonshotai/Kimi-K3</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Quantify it: 'How many orders per day, and minutes per order?'
- That is exactly the kind of manual retyping we remove; no AI needed.
- Mention EUR 500 workflow assessment gives cost per process and fixed quote.
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We don't bill hours. Fixed price, scope and date agreed before any code.
- Delays are our cost, not yours. That's the point of fixed price.
- "Want me to explain how the 18-month payback guarantee works?"

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Forty cents per document is pay-per-use at their price; we quote fixed, agreed before code.
- Per-document fees scale with your order volume; our fixed price doesn't.
- "How many orders per day? Then we can compare forty cents against a fixed quote."
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- That's why we fix price, scope and date before any code; overruns are our cost.
- And the 18-month payback guarantee: it pays for itself or we pay the difference.
- "What did that overrun end up costing you?"

**Prospect:** Is our data going to leave the Netherlands?  
- No: Dutch-hosted, open-source models; no outside AI provider sees your documents.
- Mutual NDA before the assessment, data processing agreement before the build.
- "Want that in writing before we start?"

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaking means manual fixes; we build stable connections between email and Exact.
- Fixed price, no surprise overruns like your last IT company.
- Ask: 'How much time do your three people spend fixing Zapier errors?'
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Offer the free 30-min discovery call with both owners, no commitment.
- "Would it help if I joined that conversation with your co-owner?"

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We don't bill hours. Fixed price, scope and date agreed before any code.
- Delays are our cost, not yours. That addresses the budget overrun worry.
- "Shall we start with the EUR 500 assessment? You get a fixed quote per automation."

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "Three people manually typing orders from email into Exact",
  "Zapier integration keeps breaking",
  "Previous IT company went way over budget"
 ],
 "objections": [
  {
   "topic": "hourly rate / pricing model unclear",
   "status": "open"
  },
  {
   "topic": "data leaving the Netherlands",
   "status": "open"
  },
  {
   "topic": "budget overrun concern from past vendor",
   "status": "open"
  }
 ],
 "companies": [
  "Exact",
  "Flowbase",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>google/gemma-3-27b-it</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- “What’s the approximate number of orders these three people process each day?”
- Focus on the time wasted: typing into Exact is time not spent on other tasks.
- Mention the workflow assessment: EUR 500 fixed price to quantify the cost.
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- Reframe: Koref buys outcomes, not hours. Focus on the cost of the typing.
- Ask: "What does that typing cost you per year?" Use the cost formula.
- Mention: Koref offers fixed price and a payback guarantee, avoiding hourly risk.
- _research:_ Exact

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Flowbase's per-document cost adds up quickly; focus on total yearly cost.
- Koref offers fixed price and a payback guarantee, not pay-per-use.
- “What’s the total yearly cost of those 3 people typing into Exact?”
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Acknowledge their concern: 'Over budget is frustrating, we offer fixed price builds.'
- Highlight the 18-month payback guarantee: 'We guarantee a return, or Koref refunds the difference.'
- “What’s the approximate yearly cost of those three people typing into Exact?”
- _research:_ Exact

**Prospect:** Is our data going to leave the Netherlands?  
- Reassure them: Dutch-hosted, open-source models, mutual NDA before assessment.
- Contrast with Flowbase: fixed price, not pay-per-document at their price.
- “What’s the total volume of orders processed monthly?”
- _research:_ Flowbase

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaking sounds costly. What's the impact of each failure in time/money?
- Koref offers fixed price and date, unlike Zapier, avoiding budget overruns.
- We host open-source models in the Netherlands; your data stays here.
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Mention the workflow assessment: EUR 500 fixed price, report with payback estimate.
- Reiterate data security: Dutch-hosted, open-source models, mutual NDA before assessment.
- “What’s the approximate yearly cost of those three people typing into Exact?”
- _research:_ Flowbase

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- Reiterate: Koref offers fixed price, scope, and date, no hourly rates.
- Mention the 18-month payback guarantee: outcomes, not hours, are what you buy.
- “What’s the total yearly cost of those 3 people typing into Exact?”
- _research:_ Flowbase

**Call memory:**

```json
{
 "budget": "Concerned about going over budget with IT costs.",
 "decision_makers": [
  "Co-owner"
 ],
 "pains": [
  "Manual order entry is time consuming.",
  "Zapier integration is unreliable."
 ],
 "objections": [
  {
   "topic": "Pricing",
   "status": "open"
  },
  {
   "topic": "Data location",
   "status": "open"
  }
 ],
 "companies": [
  "Flowbase",
  "Zapier",
  "Exact"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>deepseek-ai/DeepSeek-V4-Flash-0731</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Name the cost: 3 people x hours x 230 days; ask how many minutes each.
- That's a classic two-systems gap, email to Exact, no AI needed.
- Offer the EUR 500 assessment to quantify savings and a fixed quote.
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- They're probing cost, anchor on the 18-month payback guarantee, not rates.
- Say: 'We price fixed, so you know the cost before we start.'
- Ask: 'What's the yearly cost of those three mornings?'

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Flowbase charges per document; we charge fixed price with an 18-month payback guarantee.
- Ask: "What does Flowbase's 40 cents per document include, setup, support, liability?"
- Their per-document cost grows with volume; our fixed price doesn't.
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Acknowledge the fear: fixed price, scope and date agreed before any code.
- Overruns are our cost, not yours; delays are Koref's problem.
- Ask: 'Would a fixed quote with an 18-month payback guarantee change that?'

**Prospect:** Is our data going to leave the Netherlands?  
- Reassure: Dutch-hosted, open-source models, mutual NDA before assessment.
- Data stays on infrastructure you or we control; no outside AI provider sees it.
- "Want me to put that in writing in the data processing agreement?"

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaking is exactly the two-systems-not-talking problem we fix.
- We take operational liability after go-live, so it stays fixed.
- "Want us to map the Zapier failures into the workflow assessment?"
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Offer a free 30-min discovery call with both owners to settle it.
- Ask: 'What would your co-owner need to see to say yes?'
- Mention the 18-month payback guarantee covers their over-budget fear.

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We don't bill hourly, fixed price agreed before any code, so no overrun risk.
- Cost is based on the yearly saving, not hours; e.g. 3 people x 30 min/day x 230 days.
- "Want me to walk through the math on your Exact order entry?"
- That's how we avoid what happened with your last IT company.

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "manual order entry from email into Exact",
  "Zapier keeps breaking"
 ],
 "objections": [
  {
   "topic": "pricing model",
   "status": "open"
  },
  {
   "topic": "data residency",
   "status": "open"
  },
  {
   "topic": "past IT vendor over budget",
   "status": "open"
  }
 ],
 "companies": [
  "Flowbase"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>zai-org/GLM-5.3</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Quantify it: 3 people x ~2 hours x ~EUR 48/hr x 230 days is well over EUR 10,000/yr.
- Offer the EUR 500 workflow assessment: fixed quote per automation, report in 2 days.
- "How many orders come in per morning, roughly?"
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We don't bill hourly; fixed price, scope and date agreed upfront.
- Overruns are our cost, not yours.
- "Want me to walk through what a fixed quote for the email-to-Exact work looks like?"

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Compare total yearly cost: 40 cents per doc adds up fast at volume
- Koref is fixed price, no per-document meter running forever
- "Roughly how many order emails do you get per day?"
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- That's exactly why we work fixed price, scope and date agreed upfront.
- Any delay or overrun is our cost, not yours.
- "What did the overbudget project cost you in the end?"

**Prospect:** Is our data going to leave the Netherlands?  
- No: Dutch-hosted, open-source models, no outside AI provider sees documents.
- Contrast Flowbase: fixed price, not per-document fees that grow with volume.
- Ask: "Who owns the go/no-go, you or your co-owner?"

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaking is exactly the two-systems problem we fix, not patch.
- We fix price, scope and date upfront; overruns are our cost, not yours.
- "What exactly breaks in Zapier, the email side or the Exact side?"
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Offer the EUR 500 assessment: report and fixed quote to share with your co-owner.
- Address over-budget fear: fixed price, scope and date agreed before any code.
- Ask: 'Would a 30-minute call with your co-owner next week work?'

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- No hourly rate: fixed price, scope and date agreed before any code.
- Overruns are Koref's cost, that answers your last IT company worry.
- EUR 500 assessment gives a fixed quote and payback math for the Exact typing.

**Call memory:**

```json
{
 "budget": "Concerned about going over budget; comparing to Flowbase at 40 cents per document",
 "decision_makers": [
  "Co-owner must be consulted"
 ],
 "pains": [
  "Three people spend mornings typing email orders into Exact",
  "Zapier automation keeps breaking"
 ],
 "objections": [
  {
   "topic": "Pricing / hourly rate unclear",
   "status": "open"
  },
  {
   "topic": "Previous IT company went over budget",
   "status": "open"
  },
  {
   "topic": "Data staying in the Netherlands",
   "status": "open"
  },
  {
   "topic": "Competing offer from Flowbase",
   "status": "open"
  }
 ],
 "companies": [
  "Exact",
  "Flowbase",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>deepseek-ai/DeepSeek-V4.1-Flash</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Quantify: 3 people x morning hours x ~EUR 48/hr loaded.
- Tie to Exact: email orders auto-entered, no retyping.
- "How many orders per day land in that inbox?"
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- Don't quote hours; pivot to fixed price and payback guarantee.
- "What does one order cost you in time today?"

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Flowbase charges per document; you'd own nothing and pay forever.
- Fixed price, fixed date, 18-month payback guarantee instead.
- "What does forty cents per document add up to per year?"
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Acknowledge the overrun; fixed price and date agreed before code.
- "What did that project end up costing you in total?"
- Delays are our cost, not yours, that's the point.

**Prospect:** Is our data going to leave the Netherlands?  
- Dutch-hosted, open-source models; no outside AI provider sees documents.
- Mutual NDA before assessment, processing agreement before build.
- "Would a Dutch-hosted setup remove that concern for your co-owner?"

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaks because it's glue, not a system, say that plainly.
- "What happens on the mornings it breaks, who fixes it?"
- Fixed price, fixed date: no overrun risk like last IT company.
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Good sign: co-owner is the real decision maker. Lock a next step.
- "What would your co-owner need to see to say yes?"
- Offer the EUR 500 assessment; report is theirs to share.

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- Don't quote a rate: fixed price, scope, date agreed up front.
- "What would it be worth to stop the 3 people typing orders?"
- Overruns are our cost, not yours, like the last IT company.

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "three people spend most of their morning typing incoming orders from email into Exact",
  "Zapier keeps breaking",
  "last IT company went way over budget"
 ],
 "objections": [
  {
   "topic": "pricing model unclear",
   "status": "open"
  },
  {
   "topic": "data leaving the Netherlands",
   "status": "open"
  },
  {
   "topic": "needs to discuss with co-owner",
   "status": "open"
  }
 ],
 "companies": [
  "Exact",
  "Flowbase",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>zai-org/GLM-5.3-Flash</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Quantify it: 3 people x minutes per order x orders daily.
- Run the cost formula live, likely well over EUR 10,000/yr.
- Ask: "How many orders come in on a typical morning?"
- This is exactly two systems not talking, classic Koref fit.

**Prospect:** What's your hourly rate?  
- We don't bill hourly, fixed price and scope agreed upfront.
- Say: "If the numbers work, the €500 assessment gives you a fixed quote."
- Pivot back: three people, every morning, that's worth quantifying.

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Per-document pricing scales with volume; ours is fixed regardless.
- Ask: "How many documents per day would that be?"
- Note who carries the risk if volume or errors grow.
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- That's why we quote fixed price and scope before any code.
- Delays are our cost, not yours, overrun risk is ours.
- "What would a fixed price for that Exact order entry be worth to you?"

**Prospect:** Is our data going to leave the Netherlands?  
- No: Dutch-hosted, open-source models, no outside AI provider sees documents.
- Offer NDA before assessment and data processing agreement before build.
- "What does Flowbase's 40 cents include, support and fixes?"

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaking fits our point: fragile glue between systems.
- Offer a fixed-price build replacing it, with liability after go-live.
- "How much time do those three spend each morning?"
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Offer the EUR 500 assessment report as something concrete to show the co-owner.
- The report stays theirs even if you don't proceed.
- "What would your co-owner want to see before saying yes?"

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We don't bill hourly, fixed price and scope agreed before any code.
- Start with the EUR 500 workflow assessment; report is yours to keep.
- "What would 3 people typing orders into Exact cost you yearly?"

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner (not present on call)"
 ],
 "pains": [
  "Three staff manually typing email orders into Exact",
  "Zapier automations keep breaking"
 ],
 "objections": [
  {
   "topic": "pricing unclear (hourly rate question unanswered)",
   "status": "open"
  },
  {
   "topic": "past IT vendor went over budget",
   "status": "open"
  },
  {
   "topic": "data leaving the Netherlands",
   "status": "open"
  }
 ],
 "companies": [
  "Exact",
  "Flowbase",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>Qwen/Qwen3-235B-A22B-Instruct-2507</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Saves ~3 hours/day. At EUR 48/hr, that's ~EUR 33,000/year.
- That's exactly the kind of task we fix: connect email to Exact.
- Want a fixed quote to automate this within 18 months payback?
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We don't bill by the hour. Fixed price, fixed scope, fixed date.
- The build pays for itself within 18 months or we pay back the difference.
- “Is freeing up three mornings a week a priority for the co-owner?”

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Flowbase charges per document; we charge a fixed price to eliminate the task entirely
- Ask: "Are you comparing fixed cost to remove work, or ongoing per-item fees?"
- Exact integration is included in our fixed quote, no per-use fees
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- Fixed price, scope and date agreed upfront, delays are Koref's cost, not yours
- The build pays for itself within 18 months or Koref pays back the difference
- We take operational liability after go-live, unlike most hourly suppliers
- _research:_ Flowbase

**Prospect:** Is our data going to leave the Netherlands?  
- Data stays in the Netherlands, on Dutch-hosted infrastructure
- Open-source models, no external AI providers see your data
- We sign an NDA before the assessment

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaks when systems change; we build stable, maintained connections
- Our fix includes monitoring and liability, no more surprise breakdowns
- Have the co-owner compare our 18-month payback guarantee with Flowbase's per-document cost?
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- "What’s the main thing you’ll discuss with your co-owner?"
- _research:_ Flowbase

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We don't bill hourly. Fixed price, fixed scope, fixed date.
- If it doesn't pay for itself in 18 months, we pay you back.
- The assessment shows exactly what it costs and what you save.
- _research:_ Flowbase

**Call memory:**

```json
{
 "budget": "Concerned about going over budget; comparing pricing models",
 "decision_makers": [
  "Co-owner"
 ],
 "pains": [
  "Spending mornings typing orders from email",
  "Zapier keeps breaking",
  "IT project went over budget before"
 ],
 "objections": [
  {
   "topic": "Pricing model unclear",
   "status": "open"
  },
  {
   "topic": "Data stays in Netherlands",
   "status": "answered"
  }
 ],
 "companies": [
  "Flowbase"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>nvidia/Nemotron-3_5-Lightning</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- "How many orders per morning?"
- Ask about the time cost per order
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- "What's the total time you spend on this each week?"
- Ask about their current Exact setup and any integration needs.
- _research:_ Exact

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- "Forty cents per doc?"
- Show how 3 staff x 2 hours saves EUR 1,200/mo vs Flowbase
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
_not valid JSON:_ `{"bullets": ["\"Fixed price, scope and date agreed before any code\"", "Ask: \"What went over budget last time?\"", "Reassure: \"18-month payback guarantee\"], "company": "Exact"}`

**Prospect:** Is our data going to leave the Netherlands?  
- "No, we host all data in Dutch data centers."
- Mention open-source models keep data local.
- _research:_ Exact

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- "Zapier breaks? That's the weak link."
- Ask: "What exactly breaks and when?"
- Mention: "Exact and Zapier not talking?"
- _research:_ Flowbase

**Prospect:** I'd need to discuss this with my co-owner first.  
- "Can we schedule a quick 15-min call with your co-owner?"
- Ask about the 40c/document Flowbase quote: "Does that include Exact integration?"
- _research:_ Exact

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- "Fixed price, scope and date before any code"
- 18-month payback guarantee: we cover the difference if savings don't meet target
- _research:_ Exact

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "typing incoming orders from email into Exact",
  "Zapier keeps breaking",
  "last IT company went over budget"
 ],
 "objections": [
  {
   "topic": "hourly rate pricing",
   "status": "open"
  },
  {
   "topic": "data leaving Netherlands",
   "status": "answered"
  }
 ],
 "companies": [
  "Flowbase"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>nvidia/nemotron-3-super-120b-a12b</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Three people typing emails into Exact daily, how many orders does that cover?
- What’s the average time per order? We’ll calculate the yearly cost together.
- If that time were automated, could those three focus on higher-value work?
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We don't do hourly, fixed price + 18‑month payback guarantee eliminates overrun risk.
- Ask: "Would seeing a fixed quote and savings timeline help us move forward?"

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
- Forty cents per doc adds up fast, let’s compare total monthly cost vs our fixed-price build.
- Our workflow assessment shows exact savings per order typed into Exact, no per-doc guesswork.
- Want me to walk through how we calculate yearly cost for those 3 people typing orders?
- _research:_ Flowbase

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- We fix that with a fixed price, no overruns, ever.
- Our 18‑month payback guarantee means if it doesn’t save, we refund the difference.
- "How does a fixed quote protect you from going over budget?"
- _research:_ Exact

**Prospect:** Is our data going to leave the Netherlands?  
- Your data stays in the Netherlands, our models and hosting are Dutch‑hosted.
- "Would you like to see our data‑processing agreement before we start?"
- We sign a mutual NDA and DPA before any work begins.

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaks, our fix runs on your terms, no third-party limits.
- We connect email to Exact directly, like you asked, with Dutch-hosted reliability.
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Understood, discussing with your co-owner makes sense. When’s a good time to reconvene?
- To recap: three people manually entering email orders into Exact each morning, taking most of their morning.
- We fix that with a fixed-price automation, 18-month payback guarantee, and Dutch-hosted, open-source AI, no data leaves the Netherlands.

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
_not valid JSON:_ `We charge a fixed price based on workflow savings, no hourly rates. Your co-owner will see the full quote after the free discovery call.`

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "typing incoming orders from email into Exact",
  "Zapier keeps breaking"
 ],
 "objections": [
  {
   "topic": "pricing confusion",
   "status": "open"
  },
  {
   "topic": "data leaving Netherlands",
   "status": "open"
  }
 ],
 "companies": [
  "Flowbase"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>zai-org/GLM-5.1</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Run the cost: 3 people × ~2.5 hrs × €48/hr × 230 days ≈ €83K/yr, well above build threshold
- Stress fixed price, not hourly: scope and date agreed before any code
- "What happens when one of those three is out sick?"
- _research:_ Exact

**Prospect:** What's your hourly rate?  
_not valid JSON:_ `- "We work fixed price, not hourly, delays are our cost, not yours."
- "How many hours do those three people spend each morning on Exact?"`

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
_not valid JSON:_ `- We work fixed price per build, not per document, no usage risk for you.
- "How does Flowbase handle it if their pricing model changes?"
- With our 18-month payback guarantee, you carry no overrun ris`

**Prospect:** Honestly the last IT company we worked with went way over budget.  
_not valid JSON:_ `- Fixed price, scope and date agreed upfront; overruns are our cost, not yours.
- "What did that previous project go over budget on?"
- 18-month payback guarantee protects your investment if savings f`

**Prospect:** Is our data going to leave the Netherlands?  
_not valid JSON:_ `- Data stays in NL on open-source models; no outside AI provider sees your documents.
- Fixed price means zero overrun risk, unlike your last IT company.
- "Would Dutch-hosted data and a fixed price a`

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
_not valid JSON:_ `- Zapier breaking is exactly why we fix scope and price upfront; overruns are our cost.
- "How often does Zapier break, and what happens to those orders?"
- We connect systems directly; no fragile mid`

**Prospect:** I'd need to discuss this with my co-owner first.  
_not valid JSON:_ `- Acknowledge the co-owner decision; offer a short summary for them.
- "Should I join that call to answer any questions directly?"
- Highlight: fixed price removes the budget-overrun risk you mentione`

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
_not valid JSON:_ `- We don't bill hourly; fixed price and date, so overruns are our cost.
- "Want me to walk through the fixed-price quote from the assessment?"
- Data stays Dutch-hosted; no outside AI provider sees yo`

**Call memory:**

```json
{
 "budget": "Previous IT company went over budget; comparing to Flowbase at 40 cents per document",
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "Three people spend mornings typing email orders into Exact",
  "Zapier keeps breaking"
 ],
 "objections": [
  {
   "topic": "Hourly rate / pricing model unclear",
   "status": "open"
  },
  {
   "topic": "Previous IT company went over budget",
   "status": "open"
  },
  {
   "topic": "Data leaving the Netherlands",
   "status": "open"
  }
 ],
 "companies": [
  "Exact",
  "Flowbase",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>MiniMaxAI/MiniMax-M3</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
- Classic Koref fit - two systems not talking, no AI hype needed.
- Ask: 'How many orders per morning, and minutes per order?'
- EUR 500 workflow assessment quantifies it and gives a fixed quote.
- _research:_ Exact

**Prospect:** What's your hourly rate?  
- We don't bill hourly, fixed price, scope and date agreed upfront.
- Three people, every morning, that's the cost we measure against.
- "Roughly how long does each order take to type in?"

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
_not valid JSON:_ ``

**Prospect:** Honestly the last IT company we worked with went way over budget.  
- That's exactly why we work fixed price, no overrun risk for you.
- Overruns are our cost, covered by the 18-month payback guarantee.
- "Want me to walk through how the fixed quote works?"

**Prospect:** Is our data going to leave the Netherlands?  
- No, data stays in the Netherlands on Dutch-hosted infrastructure.
- Open-source models only; no outside AI provider sees your documents.
- NDA before the assessment, data processing agreement before any build.

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
- Zapier breaks often; Koref takes operational liability once it's live.
- Zapier is fragile glue; Koref builds a real, monitored bridge.
- Ask: "What part of the Zapier flow keeps breaking?"
- _research:_ Zapier

**Prospect:** I'd need to discuss this with my co-owner first.  
- Makes sense, invite your co-owner to the free 30-min discovery call.
- The EUR 500 assessment ends with a fixed quote they can review.
- "Want a one-page summary to share with them?"

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
_not valid JSON:_ ``

**Call memory:**

```json
{
 "budget": null,
 "decision_makers": [
  "co-owner"
 ],
 "pains": [
  "Three people spend mornings manually typing email orders into Exact",
  "Zapier keeps breaking for some automation tasks",
  "Previous IT vendor went significantly over budget"
 ],
 "objections": [
  {
   "topic": "Data leaving the Netherlands",
   "status": "open"
  },
  {
   "topic": "Pricing model unclear, asked hourly rate twice",
   "status": "open"
  },
  {
   "topic": "Past IT project went over budget",
   "status": "open"
  }
 ],
 "companies": [
  "Exact",
  "Flowbase",
  "Zapier"
 ],
 "timeline": null
}
```

</details>

<details><summary><b>moonshotai/Kimi-K2.7-Code</b></summary>

**Prospect:** So basically we have three people who spend most of their morning typing incoming orders from email into Exact.  
_not valid JSON:_ ``

**Prospect:** What's your hourly rate?  
_not valid JSON:_ ``

**Prospect:** We're also talking to Flowbase, they said it would be about forty cents per document.  
_not valid JSON:_ ``

**Prospect:** Honestly the last IT company we worked with went way over budget.  
_not valid JSON:_ ``

**Prospect:** Is our data going to leave the Netherlands?  
_not valid JSON:_ ` {"bullets": ["No: your data stays in the Netherlands, Dutch-hosted.", "Open-source models on infrastructure you or Koref control.", "No outside`

**Prospect:** Right now we use Zapier for some of it but it keeps breaking.  
_not valid JSON:_ ``

**Prospect:** I'd need to discuss this with my co-owner first.  
- Ask: 'Can we schedule a 30-minute call with your co-owner this week?'
- Offer to send a one-page brief on Exact automation, fixed price, Dutch hosting.
- Propose the EUR 500 assessment as a joint, low-risk next step.

**Prospect:** Sorry, what's your hourly rate again? I still don't get how you price this.  
- We don't bill hours; fixed price before we build.
- EUR 500 assessment gives a fixed quote and 18-month payback guarantee.
- How many email orders do three people type into Exact daily?

**Call memory:**

```json

```

</details>
