# Contributing

* Run `python -m unittest discover -s tests` before sending a change; CI runs it on Ubuntu and Windows.
* A change that can move accuracy needs the numbers to move with it: run `./unredact.sh evaluate`, then
  `python tools/build_site.py`, and commit `results/results.json` and `results/cases.json`.
* Settings are tuned with `./unredact.sh evaluate --calibrate` only. Never tune on the test books.
* Docs say only what a command in this repository measures. "Not measured" is a fine thing to write.
* No real people's names in examples or test data; `corpus/names.txt` has stand-ins.
