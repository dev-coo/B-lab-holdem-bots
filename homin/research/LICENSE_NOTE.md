# External Data — License & Provenance

## Kaggle — `kaggle/poker-heads-up`

- **URL**: https://www.kaggle.com/datasets/kaggle/poker-heads-up
- **License**: Attribution 4.0 International (CC BY 4.0)
- **Download date**: 2026-04-19
- **Local path**: `data/raw/poker-heads-up.zip`, `data/raw/poker/*.txt`
- **Size**: 101 MB zipped, 105 files extracted
- **SHA256 (zip)**: `2708a34b43cddb72dacefe877feeb2b9c7ad51121ba25f9873cea2b8cd6b9599`

### Description
LLM vs LLM heads-up No-Limit Hold'em hand histories, PokerStars-style text format. Each file contains matches between two specific LLM opponents (e.g., `Claude_Opus_4.5_vs_Claude_Opus_4.6.txt`). 105 matchups across ~15 LLM models.

### Format Characteristics
- **Game**: No-Limit Texas Hold'em (NLHE) — compatible with our server
- **Players**: 2 (heads-up) — limited transfer to 4-9 player games
- **Stacks**: 200 chips/hand ($1/$2 blinds = 100 bb), cash game format (stack resets per hand) — different from our tournament
- **Cards notation**: `[8c Ac]` space-separated — compatible with BOT_GUIDE §3

### Attribution
Data published on Kaggle by the `kaggle` organization account under CC BY 4.0. Use is restricted to this research and cited as above. Derivative parameter files (`configs/*.yaml`) will include provenance pointer back to this note.

---

## BOT_GUIDE
- **Source**: `guide/BOT_GUIDE.md`
- **SHA256**: `5e706f217e193ec68f65fc6b334493c0784e44f74f7ad71325caabd8cace82b9`
- **License**: Internal project document (운영자 제공).
