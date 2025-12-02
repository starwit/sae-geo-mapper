# SAE GEO Mapper

A SAE stage that maps object locations from camera / pixel space to geo-coordinate space. For that it needs to be configured with a number of optical and geometrical camera parameters.\

Geo Mapper can be run in two fundamental modes: `copy` and `map`. `copy` means, that all detections of an incoming `SaeMessage` are set to the geo location of the camera from that message (i.e. being mapped to a point that is the camera location). `map` means that camera location is also being read from the video frame, but then actual geo-mapping is performed, i.e. detections are mapped from image space into geo space, according to all configured camera parameters.

## How to run with arbitrary python versions
- Make sure `pyenv` is installed
- Install the Python version you want to test: `pyenv install 3.11.9`
  - If you encounter installation error, check that you have all Python build dependencies installed (refer to pyenv README)
- Set the installed Python version for this shell, e.g. `pyenv shell 3.11.9`
- Run `poetry install`, it should automatically pick up the correct Python version (as long as it satisfies the version constraints in `pyproject.toml`) and use it for the virtualenv

## How to Build

See [dev readme](doc/DEV_README.md) for build & package instructions.

## Input/Output
- **Input** message must be a `SaeMessage`. The geo-mapping is done on each `Detection` message within. If there are no `Detection` messages, the processing is effectively a no-op. If `camera_location` is not set, the message is dropped.
- **Output** is the input `SaeMessage` with geo-coordinates added to every `Detection`. All other fields are preserved.

# Changelog
## 1.0.0
- Refactor config and slightly change the role of this component within the SAE. Camera location data has now been fully moved to the position-source.
  - `copy` and `map` mode
  - Refuses to forward messages without camera location
  - Remove option to pass through messages unaltered
- Breaking config change (due to role change above): As the previous combinations of config options was very hard to digest, describing a way to migrate the configuration for all cases would be unnecessary cumbersome and not entirely helpful. It is therefore best to recreate the config starting at the 1.0.0 config template.
## 0.7.0
- Upgrade `vision-api` to `3.1.0`
- Add `SaeMessage.frame.camera_location` if `pos_lat` and `pos_lon` is set (independent of `passthrough` mode)