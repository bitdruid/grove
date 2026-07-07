Possible features and gaps, carried over from the original PHP project. Reference names in parentheses point at the original module / DB table. Contributions and feature requests welcome.

## Recon / scraping tasks

- [ ] HTTP / webserver info — headers, status, banner (`webserver` / `tbl_webserver`)
- [ ] Web technology detection — Wappalyzer-style fingerprinting (`webtechnology` / `tbl_webtechnology`)
- [ ] SSL/TLS certificates — issuer, chain, validity (`certs` / `tbl_cert`)
- [ ] DNS mail records — MX/SPF/DMARC/nameservers (`recordsmail` / `tbl_recordsmail`)
<!-- - [ ] Reverse IP — other domains on the same host (`reverseip` / `tbl_reverseip`) -->
- [ ] IP history — historical IP changes (`iphistory` / `tbl_iphistory`)
- [ ] Port scan (nmap) — quick + full (`nmap` / `tbl_nmap`)
- [ ] Blacklist / DNSBL — Spamhaus/abuseat reputation (`blacklist` / `tbl_blacklist`)
- [ ] Malware scan (`malware`)
- [ ] Cryptocurrency wallet extraction — BTC/ETH (`cryptocurrency`)
- [~] Contacts extraction (`contacts` / `tbl_contacts`) — email done (IANA-TLD validated → `c_code_mail`); phone still open
- [ ] Accounts / social handles (`accounts` / `tbl_accounts`)
- [ ] Search-engine texts — SERP harvesting (`searchengine` / `tbl_searchengine`)
- [ ] Image gallery generation (`codeimagegallery` / `tbl_imagegallery`)
- [ ] CSV export of DB tables (`export`) — grove only has the offline ZIP

## Partially stubbed (column exists, never populated)

- [x] EXIF — batch exiftool → `c_code_exif`; GPS tags mirrored into `c_code_gps`
- [ ] Phone numbers — `tbl_code.c_code_phone` column exists, no extractor populates it

## Platform / system features

<!-- - [ ] Presets — `basic`/`fast`/`full` + CRUD (`tbl_system_preset`) -->
- [ ] Toolkit page — standalone one-shot tools outside the job pipeline (`toolkit`)
- [ ] Helpers: perceptual image hashing / dedup, rotating API/DNS proxy
