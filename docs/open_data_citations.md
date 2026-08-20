# MARSAD — Open Data Citation Sheet

**UAE Hackathon 2026 · Track 1 HackArena · Challenge #9**  
Securities and Commodities Authority (now the **UAE Capital Market Authority**) · Vertech Creations FZCO

> Generated from `services/core/marsad_core/data/uae_open_data.py`, the same module the
> dashboard and the calculations read. The citation sheet cannot drift from the numbers.

**12 government sources** · 8 figures read directly at source · 3 dataset pages confirmed · 1 official statement via wire · 3 with machine-readable access

## The gap in the national data

No UAE open dataset publishes cyber incidents broken down by financial sector entity. The CBUAE Financial Stability Report names cyber risk as systemic without quantifying it. That absence is the gap MARSAD fills, and stating it is more defensible than inventing a source.

## Sources

### Annual Report 2025 — Table 4: Total Number of Licensees by Type in 2025

- **Publisher:** Central Bank of the United Arab Emirates (CBUAE)
- **Portal:** `centralbank.ae`
- **URL:** https://www.centralbank.ae/media/4qbn11cl/annual-report-2025-en.pdf
- **Access:** PDF
- **Coverage:** as at 31 December 2025 · last updated 2025-12-31
- **Provenance:** `VERIFIED`
- **Used for:** Sector cohort sizes. Sets the k-anonymity floor per sector and identifies which cohorts are too small to publish at all and must be pooled.
- **Verified figures:**
    - total licensees: **856**
    - banks: **61**
    - finance companies: **20**
    - exchange businesses: **64**
    - fintech companies: **48**
    - insurance companies: **58**
    - insurance brokers: **161**
    - third-party administrators: **20**

### CB Register — monthly register of licensed financial institutions

- **Publisher:** Central Bank of the United Arab Emirates (CBUAE)
- **Portal:** `centralbank.ae`
- **URL:** https://www.centralbank.ae/media/kxxkzrho/cb-register-march-2026.pdf
- **Access:** PDF
- **Coverage:** monthly series; issues verified from Sept 2022 to April 2026 · last updated 2026-03
- **Provenance:** `VERIFIED`
- **Used for:** The participant registry and the sustainability half of the data claim: a monthly re-publication means cohort sizes and the concentration denominator are recomputed every month rather than frozen at launch.
- **Verified figures:**
    - banks (Mar 2026): **62**
    - exchange companies: **64**
    - retail payment services: **32**
    - stored value facilities: **17**
    - finance companies: **20**

### UAE Monetary, Banking & Financial Markets Developments Report, Q4 2025

- **Publisher:** Central Bank of the United Arab Emirates (CBUAE)
- **Portal:** `centralbank.ae`
- **URL:** https://www.centralbank.ae/media/2cyhdr5b/uae-monetary-banking-financial-markets-dev-report-e-q4-2025.pdf
- **Access:** PDF
- **Coverage:** Q4 2025 (quarterly series) · last updated 2025-Q4
- **Provenance:** `VERIFIED`
- **Used for:** Converts a dimensionless concentration score into national exposure in AED. One government publication carrying both exchanges in one place.
- **Verified figures:**
    - ADX market capitalisation: **AED 3,104.0 bn**
    - ADX quarterly traded value: **AED 125.7 bn**
    - DFM market capitalisation: **AED 980.0 bn**
    - DFM quarterly traded value: **AED 37.3 bn**
    - total bank assets: **AED 5,339.9 bn**

### TDRA Open Data — Phone & Internet Subscriptions; Indicators of ICT Access and Use

- **Publisher:** Telecommunications and Digital Government Regulatory Authority (TDRA)
- **Portal:** `tdra.gov.ae`
- **URL:** https://tdra.gov.ae/en/open-data/data-sets
- **Access:** XLSX
- **Coverage:** December 2025 release; 61 datasets across 10 categories · last updated 2026-05-08
- **Provenance:** `PAGE_VERIFIED`
- **Used for:** The only current, unauthenticated, machine-readable feed in this set. Scales the attack-surface denominator and sizes realistic incident submission volumes for the pilot.
- **Verified figures:**
    - datasets published: **61**
    - access: **direct XLSX URLs, no authentication**
- **Caveat:** Dataset pages and stable download URLs confirmed; individual cell values not yet parsed, so no figure from inside these workbooks is quoted.

### Monthly UAE Security Report (aeCERT)

- **Publisher:** TDRA — aeCERT
- **Portal:** `tdra.gov.ae`
- **URL:** https://tdra.gov.ae/en/aecert/resource-center/statistics
- **Access:** PDF
- **Coverage:** monthly; downloadable issues on the page are July–December 2020 · last updated 2020-12
- **Provenance:** `VERIFIED`
- **Used for:** Supplies the national incident-type taxonomy and an empirical monthly incident rate used to calibrate expected submission volume.
- **Verified figures:**
    - attacks responded to (Apr 2020, federal government scope): **~34,000**
    - incidents handled: **197**
    - composition: **vulnerabilities 47% / malware 46% / phishing 7%**
- **Caveat:** Current-year issues are not published on the statistics page; the 2024 and 2025 filters return no downloadable items. Quoted figures are 2020.

### Licensed Companies — Open Data

- **Publisher:** Securities and Commodities Authority, now UAE Capital Market Authority (CMA)
- **Portal:** `uaecma.gov.ae`
- **URL:** https://www.uaecma.gov.ae/en/open-data/licensed-companies.aspx
- **Access:** DASHBOARD, XLSX
- **Coverage:** current register, filterable by financial activity · last updated continuous
- **Provenance:** `PAGE_VERIFIED`
- **Used for:** The authoritative enrolment universe for the challenge owner's own regulated population — the firms MARSAD would onboard.
- **Verified figures:**
    - licensed companies (CMA 2025 statement): **244**
- **Caveat:** The table renders client-side and exports to Excel; there is no public JSON/CSV endpoint. The count of 244 comes from the CMA 2025 annual statement rather than a rendered dataset page — confirm in-browser.

### CMA 2025 annual regulatory and market performance statement

- **Publisher:** UAE Capital Market Authority (CMA)
- **Portal:** `uaecma.gov.ae`
- **URL:** https://www.uaecma.gov.ae/en/media-center/news
- **Access:** HTML
- **Coverage:** full year 2025 · last updated 2026-01-27
- **Provenance:** `SYNDICATED`
- **Used for:** Average daily traded value — the flow figure that turns a provider outage into a per-day AED interruption.
- **Verified figures:**
    - average daily trading value: **AED 2.21 bn (+24.16% y/y)**
    - licences and approvals issued 2025: **3,170 (vs 1,272 in 2024)**
    - funds under CMA oversight: **197 (vs 119 in 2024)**
    - assets under management: **USD 470 bn**
- **Caveat:** Read via WAM/Reuters syndication of the CMA statement rather than a CMA-hosted page our client could render.

### ADX 2025 Results: Transformative Growth & Market Leadership

- **Publisher:** Abu Dhabi Securities Exchange (ADX)
- **Portal:** `adx.ae`
- **URL:** https://www.adx.ae/about-adx/media/adx-news/adx-market-leadership-2025-growth
- **Access:** HTML
- **Coverage:** full year 2025 · last updated 2026-01-06
- **Provenance:** `VERIFIED`
- **Used for:** Cross-validates the CBUAE market figures and supplies the investor base.
- **Verified figures:**
    - market capitalisation: **AED 3.13 trn (+4.6%)**
    - FY2025 traded value: **AED 385 bn (+12.6%)**
    - investors: **more than 1.2 million, over 200 nationalities**
    - new listings: **20**
- **Caveat:** ADX report centre (eservices.adx.ae) is disallowed by robots.txt.

### Dubai Financial Market delivers a strong 2025 performance

- **Publisher:** UAE Government Media Office / Dubai Financial Market (DFM)
- **Portal:** `mediaoffice.ae`
- **URL:** https://www.mediaoffice.ae/en/news/2026/january/28-01/dubai-financial-market-delivers-a-strong-2025-performance
- **Access:** HTML
- **Coverage:** full year 2025 · last updated 2026-01-28
- **Provenance:** `VERIFIED`
- **Used for:** Second-exchange leg of the exposure calculation and investor base.
- **Verified figures:**
    - market capitalisation: **AED 992 bn**
    - FY2025 traded value: **AED 174 bn**
    - total investor base: **1.25 million**
    - new investors in 2025: **97,394 (84% foreign)**
- **Caveat:** ADX 1.2 m and DFM 1.25 m investors overlap; neither source states they are disjoint, so they are never summed.

### Financial Stability Report 2025

- **Publisher:** Central Bank of the United Arab Emirates (CBUAE)
- **Portal:** `centralbank.ae`
- **URL:** https://www.centralbank.ae/media/kaqlwo0h/cbuae-fsr-report_2025_en.pdf
- **Access:** PDF
- **Coverage:** 2025 · last updated 2025
- **Provenance:** `VERIFIED`
- **Used for:** Establishes the whitespace. The report names cybersecurity threats as a systemic risk yet contains no quantified cyber-incident data and no third-party concentration metric — precisely what MARSAD produces.
- **Verified figures:**
    - licensed banks: **61 (23 national + 38 foreign branches)**
    - banking assets: **AED 4.6 trn (+12.0%)**
    - cited systemic risk: **AI-driven trading systems and cybersecurity threats**

### Aani instant payment platform — 12.5 million users

- **Publisher:** Central Bank of the United Arab Emirates (CBUAE)
- **Portal:** `centralbank.ae`
- **URL:** https://www.centralbank.ae/en/news-and-publications/news-and-insights/press-release/aani-delivers-a-transformational-leap-in-the-uae-s-digital-payments-landscape-12-5-million-users-and-instant-transfers-in-3-seconds/
- **Access:** HTML
- **Coverage:** as at April 2026 · last updated 2026-04-10
- **Provenance:** `VERIFIED`
- **Used for:** A named, real shared-infrastructure dependency. Aani, Jaywan and UAESWITCH are national rails every participant touches — the textbook case for concentration monitoring.
- **Verified figures:**
    - users: **12.5 million**
    - settlement: **3 seconds, 24/7**

### Bayanat — the official UAE open data portal

- **Publisher:** Federal Competitiveness and Statistics Centre (FCSC)
- **Portal:** `bayanat.ae`
- **URL:** https://bayanat.ae/en/Datasets
- **Access:** API, XLSX, CSV
- **Coverage:** thousands of federal and emirate-level datasets, 11 themes · last updated continuous
- **Provenance:** `PAGE_VERIFIED`
- **Used for:** The national catalogue. Financial and banking series here (e.g. CBUAE balance-sheet datasets) are reachable by API for Python/JS/cURL.
- **Verified figures:**
    - verified example dataset: **Balance Sheet of the Central Bank of UAE — Assets (2013–2017, XLSX + API)**
- **Caveat:** Carries no cyber-incident dataset and no register of licensed financial institutions; the Technology theme returned no datasets. The single-page app can serve a default list regardless of the dataset id, so every Bayanat citation must be re-checked in a browser.

## Derived values

### Systemic exposure basis

- Listed market capitalisation: **AED 4,084 bn** (ADX 3,104 + DFM 980)
- Average daily traded value: **AED 2.21 bn**
- Total banking assets: **AED 5,339.9 bn**

**Cross-check.** The exchanges publish full-year traded value; the CMA publishes a daily
average. Reconciling them: (ADX 385.0 + DFM 174.0)
÷ 250 trading days = **AED 2.236 bn/day** against the
CMA's reported **AED 2.21 bn/day** — two independent government
sources, within 2%.

### Privacy calibration — k derived from the licensed population

Absolute floor k=3; a cohort statistic is publishable only while contributors stay
under 10% of the cohort.

| Cohort | Population | k floor | Max contributors | Publication |
|---|---|---|---|---|
| Finance companies | 20 | 3 | 2 (< k) | **POOL REQUIRED** |
| Third-party administrators | 20 | 3 | 2 (< k) | **POOL REQUIRED** |
| FinTech companies | 48 | 3 | 4 | Sector label OK |
| Insurance companies | 58 | 3 | 5 | Sector label OK |
| Banks | 61 | 3 | 6 | Sector label OK |
| Exchange businesses | 64 | 3 | 6 | Sector label OK |
| Insurance brokers | 161 | 3 | 16 | Sector label OK |
| CMA licensed companies | 244 | 3 | 24 | Sector label OK |

*Banks are CBUAE-licensed and capital-market firms are CMA-licensed; the two registers are maintained separately, so the sum is an addressable population, not a deduplicated entity count.*

## Portals we could not reach

Published so a reviewer who cannot reproduce a citation knows it was our client, not their portal.

| Portal | Reason |
|---|---|
| `data.abudhabi` | WAF rejected the request; datasets are search-indexed |
| `dubaipulse.gov.ae` | robots.txt fetch timed out |
| `data.bayanat.ae (CKAN mirror)` | robots.txt fetch timed out |
| `eservices.adx.ae/reportcenter` | disallowed by robots.txt |
| `csc.gov.ae` | connection error on robots.txt |

Each publishes data relevant to the challenge and is search-indexed, so the datasets very
likely exist — we simply could not render them, and will not cite a figure we have not seen.
