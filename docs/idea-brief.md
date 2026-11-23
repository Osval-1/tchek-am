# WhatsApp Commerce Trust in Cameroon: Idea Brief

*Prepared 21 November 2026*

## The problem

Online selling in Cameroon happens mostly in WhatsApp groups and statuses. Sellers post product photos, buyers reply "prix ?", and payment is made upfront by MTN MoMo or Orange Money. The most common scam: the buyer is asked for an advance (or the full amount), sends it, and the seller disappears.

- Cameroonian press (Cameroon Tribune, Le360 Afrique) reports this pattern repeatedly, e.g. a buyer in Yaoundé sent half the price via Orange Money and the seller never showed up at the meeting point in Essos.
- More than 60% of adults use a mobile wallet; fewer than 20% have a bank account. Payment is almost always MoMo/OM, which offers buyers no protection.
- Most users don't know how to check a seller before paying (Cameroon Tribune interview citing ANTIC/CIRT efforts).

---

## Idea 1: Scam Alert and Seller Reputation (recommended first build)

### What it is
A **WhatsApp bot** where anyone can forward a seller's number, post or product photo **before paying** and get back a risk assessment. Over time it also gives honest sellers a **verified badge and reputation** they can show in their groups.

### Does it already exist?
| Where | Who | What |
|---|---|---|
| Cameroon | *Nothing found* | Only operator warnings (Orange, MTN), news articles, lawyers' "how to recover money" guides |
| International | ScamWarners | Lists some +237 numbers, aimed at victims abroad, not local buyers |
| Ghana | TrustGH, CyberHub Ghana | Public scam-number databases; TrustGH has 6,000+ flagged numbers and works with Ghana's Cybersecurity Authority and police |
| Nigeria | Scam Alert NG, Prembly FraudLens | Confirmed-scammer database; shared fraud data between businesses |
| Global | Truecaller Scam Checker | Check numbers, links and messages against community reports. **Main threat.** |
| Cameroon (adjacent) | Voshup (Douala) | Early-stage marketplace (pre-seed, ~$16k ask) planning escrow + AI photo search. It's a marketplace, not a trust layer for existing WhatsApp deals |

**Verdict:** the gap is real in Cameroon, and the model is proven in Ghana and Nigeria.

### How to stand out (vs Truecaller and others)
1. **Local first:** French, English and Pidgin; MoMo- and OM-specific scam patterns.
2. **Stolen photo detection (ML core):** flag product photos reused from other sellers, AliExpress or old posts.
3. **Positive reputation, not only a blacklist:** verified sellers with confirmed sales get a shareable badge.
4. **WhatsApp-native:** no new app needed for buyers.

### Core features (MVP)
- **Check a number:** forward or type a number and get the report count, how long it has been active, linked names, and confirmed-sale count.
- **Check a post or photo:** forward a product image and get "this photo appears in N other sellers' posts / matches an online catalogue image."
- **Check a message:** paste the seller's message and get it flagged for typical scam patterns (price far below market, pressure for full upfront payment, urgency, "my representative will deliver").
- **Report a scam** with evidence (see the AI submission process below).
- **Verified seller badge:** ID check, a check that the MoMo/OM account name matches, optional shop location; displayed as a link or image the seller shares.

### ML / AI components
| Component | Approach |
|---|---|
| Photo reuse detection | Image embeddings (e.g. CLIP / SigLIP) + perceptual hashing (pHash) in a vector index (FAISS / pgvector); match against submitted posts and scraped public catalogues |
| Scam text classifier | Start rules + few-shot LLM; fine-tune a small multilingual model (FR/EN/Pidgin) once you have labelled reports |
| Evidence extraction | OCR + LLM to pull phone numbers, MoMo/OM names, amounts, transaction IDs, dates from screenshots |
| Duplicate / cluster detection | Link reports that share numbers, names, MoMo account names, photos or wording, to expose scam rings using several numbers |
| Risk score | Transparent weighted score first (reports, evidence quality, age, confirmations); gradient-boosted model later once you have outcomes |

### Revenue options
- Verified seller badge (monthly fee, paid via Fapshi/MoMo).
- Partnerships with big WhatsApp selling-group admins ("verified sellers only" groups).
- Later: B2B API for fintechs, lenders and delivery companies that want to check numbers (like Prembly FraudLens).

### Risks and how to handle them
| Risk | Mitigation |
|---|---|
| **Defamation** (wrongly labelling someone a scammer) | Never say "scammer"; say "reported N times, evidence reviewed." Clear appeal process. Human review before anything becomes public |
| **Fake reports** (competitors attacking each other) | Require evidence; weight by reporter trust; one reporter can't make a number "high risk" alone |
| **Personal data** | Collect the minimum; redact the victim's details; check Cameroon's data-protection rules; get legal advice early |
| **Empty database at launch** | Launch inside a few large WhatsApp selling groups with admin partnership; seed from public reports |
| **Legitimacy** | Approach ANTIC / CIRT early, the way TrustGH works with Ghana's authorities |
| **Truecaller** | Win on local language, MoMo context, seller reputation and photo checks |

---

## Idea 2: Safer Payments for WhatsApp Deals (later phase)

### What it is
"Pay safely" links a seller can drop into any WhatsApp chat. The buyer pays, the money is held until delivery is confirmed, and then it's released to the seller.

### Why later, not first
- If **you** collect the buyer's money and pay the seller after delivery (e.g. via Fapshi or TranZak payouts), the money sits in your balance. Legally, that's **holding funds**.
- COBAC plans to raise the minimum capital for payment institutions from 500M to **1 billion FCFA** and to create a legal status for fintechs and payment service operators. Today only a handful of licensed payment institutions exist (Orange Money Cameroun, Mobile Money Corporation, plus newly licensed Konoom).
- Disputes ("the item isn't what I ordered") need human handling, which is expensive.

### How to do it safely when ready
1. Ask Fapshi / TranZak / Flutterwave (BEAC-approved via Ecobank) whether they offer a native "hold until release" feature under **their** licence.
2. Partner with a licensed institution rather than holding funds yourself.
3. Use the reputation data from Idea 1 to decide which deals need escrow (high-risk sellers) and which don't.
4. Get a fintech lawyer's opinion before launch. *(This brief is not legal advice.)*

### Alternatives that build trust without holding money
- **Verified courier, pay on delivery:** the buyer inspects the item and pays the courier; the courier is verified and rated.
- **Reputation-based trust:** Idea 1's badges and confirmed-sale history.
- **Payment-name check:** before sending, the buyer checks that the MoMo/OM account name matches the verified seller.

---

## Your questions

### Should there also be a mobile app?
**Not at first. Start with WhatsApp, then add a lightweight web page, and consider an app later.**
- Buyers won't download an app just to check one seller. WhatsApp is where the decision happens.
- Phase 1: WhatsApp bot (official WhatsApp Cloud API).
- Phase 2: a lightweight **web page** (PWA) for each verified seller's public profile and badge. This is the link sellers share. It's cheap, needs no install, and is easy to update.
- Phase 3: an **Android app** only if usage shows demand, e.g. a seller dashboard, or warnings on incoming calls and SMS. Note: Google Play heavily restricts SMS/call-log permissions, so plan around that.

### Should there be an AI-assisted submission process for reporting scammers with evidence?
**Yes. It's the heart of the product, but AI should assist and humans should decide.**

Suggested flow:
1. **Submit:** the victim sends screenshots (chat, product post, MoMo/OM confirmation SMS) to the bot.
2. **AI extracts:** OCR + LLM pull out phone numbers, account names, amounts, transaction IDs and dates, and summarise the story.
3. **AI checks:** possible tampering (edited screenshots, inconsistent fonts or timestamps); links to existing reports (same number, name, photo or wording); a quality score for the evidence.
4. **Human review:** a moderator approves before the report affects any public score. Required at least until you have reliable data.
5. **Publish carefully:** show only "reported N times, evidence reviewed, last report on [date]". Never the victim's identity.
6. **Appeal:** the reported person can contest with evidence; reports are re-reviewed.
7. **Feedback loop:** approved and rejected reports become labelled data to improve the classifiers.

Guardrails: one reporter alone can't flag a number as high risk; repeated false reporters get down-weighted; keep raw evidence private and access-controlled.

---

## Suggested next steps
1. **Customer conversations (this week):** talk to 3–5 admins of large WhatsApp selling groups and 10 buyers. Ask: Have scams hurt your group? Would you use a check-before-paying bot? Would sellers pay for a verified badge?
2. **Test Voshup** as a buyer to see what's actually live.
3. **Prototype:** WhatsApp bot + photo-reuse detection + manual report review, tested in 1–2 partner groups.
4. **Legal:** short consultation on defamation and data protection; open contact with ANTIC.

---

## Sources
- TrustGH (Ghana): https://www.modernghana.com/news/1523679/over-6000-phone-numbers-linked-to-scams-as-50.html
- CyberHub Ghana: https://dev.to/ashardrach/how-i-built-a-scam-detection-platform-for-ghana-using-django-and-paystack-3f9p
- Scam Alert NG: https://techbuild.africa/?p=44695
- Prembly FraudLens: https://techcabal.com/?p=183337
- Truecaller Scam Checker: https://techeconomy.ng/truecaller-scam-checker-suspicious-links-numbers-messages
- Voshup (VC4A): https://vc4a.com/ventures/voshup/?lang=fr
- Cameroon online-sale scams: https://afrique.le360.ma/economie/cameroun-commerce-en-ligne-et-arnaque-font-bon-menage_LAVEL6WQJ5HFBI2EGGPMUMAB3A/
- Cameroon Tribune, online commerce scams: https://cameroon-tribune.cm/article.html/66081/fr.html/commerce-en-ligne-larnaque-tisse-sa-toile
- Cameroon Tribune, cybercriminals interview: https://cameroon-tribune.cm/article.html/71790/fr.html/details_2
- Mobile wallet vs bank account figures: https://fr.allafrica.com/stories/202604080164.html
- COBAC capital reform: https://ecomatin.net/la-cobac-veut-doubler-le-capital-minimum-des-operateurs-de-mobile-money-et-creer-un-statut-pour-les-fintechs
- Licensed payment institutions in Cameroon: https://sikafinance.com/marches/cameroun-le-marche-du-mobile-money-attire-un-nouvel-acteur-venu-du-tchad_64343
- Flutterwave BEAC approval: https://www.osiris.sn/flutterwave-obtient-le-feu-vert-de-la-beac-pour-operer-au-cameroun.html
- Fapshi: https://apps.apple.com/gy/app/fapshi/id6443700859
- TranZak APIs: https://apis.io/providers/tranzak/
