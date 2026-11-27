# Offline chart calculation

Fixed lunar-javascript and iztro engines calculate explicit calendar/chart facts; facts and shensha records retain rule provenance. They do not establish predictive accuracy or make life decisions. Supported inputs use UTC+08:00 civil-standard time, or an explicitly confirmed solar-calendar `true_solar_corrected` clock supplied by the caller; calendar, leap-month, day boundary and calculation conventions remain explicit. Synthetic inputs are marked as such.

Python 3.12+ and Node.js 22+. Restore reviewed source archives with `python restore.py --output <new-external-home>`. This is offline, verifies SHA-512 and the complete engine file lock, runs no npm scripts, and refuses an existing home. Package installation itself performs no restoration. Keep the previous home to reverse the transaction.

From the new home: `node chart.mjs health`, `node chart.mjs calculate --input example.synthetic.json` for a synthetic calculation. `node render.mjs --input example.synthetic.json --output-dir <new-output> --svg-only` creates SVGs without extra modules. PNG requires separately installed sharp, optionally selected by CHART_SHARP_MODULE. No fonts, real birth records, models, accounts or host server are included. Original MIT licenses and upstream tests are under sources/ and inside the seven pinned vendor archives.

A corrected clock is used verbatim; this tool does not calculate a time correction or infer an original civil instant. Within one day of a Jie boundary it rejects the corrected-clock path and requires the original civil time. Yun dates remain provisional without that instant. These labels are preserved in SVG output. `node check.mjs` now tests this standalone adapter, without a private Life host.
