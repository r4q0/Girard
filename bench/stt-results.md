# Speech-to-text benchmark (this laptop, CPU only)

Seven local models transcribed the same 68-second spoken sales call (9 prospect lines incl. one 25-second monologue), in 2 synthetic voices (Windows David and Zira). Chunk models get audio cut at each pause or at 5 s max, like the live app will; streaming models get 100 ms pieces. Ryzen 7 8840HS, 4 threads.

- **Word errors**: % of words wrong vs the script (numbers and spelling variants like "40"/"forty" count as correct).
- **Delay per chunk**: time to transcribe one chunk after it ends (average / worst). This is added to every piece of advice.
- **CPU load**: share of one call's duration spent transcribing (0.10 = 10%).

| Model | Word errors | Delay per chunk (ms) | CPU load | Size |
| --- | --- | --- | --- | --- |
| Parakeet 0.6B | 0.6% | 363 / 753 | 0.08 | 663 MB |
| Whisper base | 1.0% | 489 / 782 | 0.10 | 452 MB |
| Parakeet 110M | 1.9% | 115 / 259 | 0.03 | 136 MB |
| Moonshine tiny | 2.2% | 108 / 178 | 0.03 | 44 MB |
| Moonshine base | 4.1% | 165 / 281 | 0.04 | 141 MB |
| Zipformer Kroko (streaming) | 4.5% | 49 / 54 | 0.04 | 71 MB |
| Nemotron streaming 0.6B | 8.3% | 142 / 163 | 0.26 | 662 MB |

## My read

- **Recommended: Parakeet 0.6B.** Most accurate (0.6% errors) and still well under a second per chunk (0.36 s average, 0.75 s worst). Real call audio is noisier than this test, so the most accurate model is the safest pick for tailored advice.
- **Speed option: Parakeet 110M.** Nearly as good (1.9%) at a third of the delay (0.12 s). Same code; switching is one line.
- **Streaming models are worse here:** they cut mid-word ("reconcil | ing", "holida | y") and Nemotron drops words, which gives the advice model broken sentences.
- **The long monologue did not stall anything:** with the 5 s cut, the worst chunk of any model was under 0.9 s.
- **Company names:** every model except Nemotron misheard "Zapier" ("Zap here", "Zapir"). Fix planned in the filter: fuzzy-match heard words against known company names (company context + research store), microseconds of work. Model hotwords were tried and crash with these model files.
- Caveat: synthetic voices on clean audio. The real test is a recorded call through the app (verification step).

## What each model heard (Zira voice)

**Parakeet 0.6B**  
So basically we have three people who spend most of their morning typing incoming orders from email into exact. | What's your hourly rate? | We're also talking to Flowbase, they said it would be about 40 cents per document. | Honestly the last IT company we worked with went way over budget. | Is our data going to leave the Netherlands? | Right now we use Zapir for some of it but it keeps breaking. | The thing is we grew from 20 to 60 people in two years and the admin side never caught up | So every Monday somebody spends the whole day reconciling invoices between the web shop and the accounting package | And when that person is on holiday, it just piles up, and our customers start calling us about missing orders. | Which honestly is embarrassing | I'd need to discuss this with my CO owner first | Sorry, what's your hourly rate again? | I still don't get how you price this.

**Whisper base**  
So basically we have three people who spend most of their morning typing incoming orders from email into exact | What's your hourly rate? | We're also talking to Flowbase. They said it would be about 40 cents per document. | Honestly the last IT company we worked with went way over budget. | Is our data going to leave the Netherlands? | Right now we use Zap here for some of it but it keeps breaking. | The thing is we grew from 20 to 60 people in two years and the admin side never caught up. | So every Monday somebody spends the whole day reconciling invoices between the webshop and the accounting package. | And when that person is on holiday it just piles up and our customers start calling us about missing orders. | which honestly is embarrassing. | I'd need to discuss this with my co-owner first. | Sorry, what's your hourly rate again? | I still don't get how you price this.

**Parakeet 110M**  
So basically we have three people who spend most of their morning typing incoming orders from email into exact. | What's your hourly rate? | We're also talking to Flow Base, they said it would be about forty cents per document. | Honestly, the last IT company we worked with went way over budget. | Is our data going to leave the Netherlands? | Right now we use Zap here for some of it, but it keeps breaking. | The thing is we grew from twenty to sixty people in two years and the admin side never caught up. | So every Monday, somebody spends the whole day reconciling invoices between the web shop and the accounting package. | And when that person is on holiday, it just piles up and our customers start calling us about missing orders. | which honestly is embarrassing. | I'd need to discuss this with my CEO owner first. | Sorry, what's your hourly rate again? | I still don't get how you price this.

**Moonshine tiny**  
So basically we have three people who spend most of their morning typing incoming orders from email into exact | What's your hourly rate? | We're also talking to Flowbase, they said it would be about 40 cents per document. | Honestly the last IT company we worked with went way over budget. | Is our data going to leave the Netherlands? | Right now we use that pier for some of it but it keeps breaking. | The thing is we grew from 20 to 60 people in two years and the admin side never caught up. | So every Monday somebody spends the whole day reconciling invoices between the webshop and the accounting package | And when that person is on holiday it just piles up and our customers start calling us about missing orders. | Which honestly is embarrassing. | I'd need to discuss this with my seal owner first. | Sorry, what's your hourly rate again? | I still don't get how you price this.

**Moonshine base**  
So basically we have three people who spend most of their morning typing incoming orders from email into exact | What's your hourly rate? | We're also talking to Flowbase, they said it would be about 40 cents per document. | Honestly the last IT company we worked with went way over budget. | Is our data going to leave the Netherlands? | Right now we use zap here for some of it but it keeps breaking | The thing is we grew from 20 to 60 people in two years and the admin side never caught up. | So every Monday somebody spends the whole day reconciling invoices between the webshop and the accounting package. | And when that person is on holiday it just piles up and our customers start calling us about missing orders. | Which honestly is embarrassing, which honestly is embarrassing, which honestly is embar | I'd need to discuss this with my co-owner first. | Sorry, what's your hourly rate again? | I still don't get how you price this.

**Zipformer Kroko (streaming)**  
so basically we have three people who spend most of their morning typing incoming orders from | email into exact | . What's your hourly rate | ? | We're also talking to flow base. They said it would be about forty cents per document | . Honestly the last IT company we worked with went way over budget | . Is our data going to leave the Netherlands | ? Right now we use Zap here for some of it but it keeps breaking | Look, the thing is we grew from twenty to sixty people in two years | and the admin side never caught up, so every Monday somebody spends the whole day reconcil | ing invoices between the web shop and the accounting package, and when that person is on holida | y it just piles up and our customers start calling us about missing orders, which honestly | is embarrassing | . I'd need to discuss this with my COWNER first | Sorry. What's your hourly rate again | ? I still don't get how you price this

**Nemotron streaming 0.6B**  
So basically we have three people who spend most of their morning typing incoming orders from email | Into exact | What's your hourly rate | Talking to Flowbase, they said it would be about forty cents per document | Honestly, the last IT company we worked with | Over budget | Is our data going to leave the Netherlands | Right | We use Zapier for some of it, but it keeps breaking | Look | Thing is, we grew from twenty to sixty people in two years, and the admin side never caught up | So every Monday somebody spends the whole day reconciling invoices between the web | The accounting package | And when that person is on holiday | Piles up and our customers start calling us about missing orders | Honestly is embarrassing | I'd need to discuss this with my CO owner first | What's your hourly rate again | I still don't get how you price this
