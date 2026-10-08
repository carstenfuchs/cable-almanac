# Cable Almanac

A tool for modeling and documenting the cable infrastructure of buildings.

Cable Almanac treats power, network, telephone, bus systems and signal lines
alike, recording where each cable starts and ends and which conduits it runs
through. The result is a clear overview of the entire installation, from the
property as a whole down to individual terminals, together with the details
needed for maintenance, troubleshooting and extensions.


## Status

Early development: Cable Almanac is being rebuilt as a Django web application,
based on an earlier YAML-based prototype.


## Setup

Requires [uv](https://docs.astral.sh/uv/), which also installs the matching
Python version:

```sh
uv sync                    # install Python and dependencies, create .venv/
ln -s .venv/bin/activate   # once: symlink for convenient activation
```
