#!/bin/bash

# docker build -t wanglabneuro/mesmerize-base:latest -t wanglabneuro/mesmerize-base:0.1.2 -f Dockerfile context
docker build -t wanglabneuro/mesmerize-base:0.2.0 -f Dockerfile_mesmerize_updated context
# docker build -t wanglabneuro/mesmerize-base:latest -t wanglabneuro/mesmerize-base:0.1.0 -f Dockerfile_update .

# Versions:
# 0.1.2 - Caiman v1.11.1, Mesmerize-core 0.4.0, Mesmerize-viz 0.1.0, Python 3.11.9
# 0.1.1 - Caiman v1.11.0, Mesmerize-core 0.4.0, Mesmerize-viz 0.1.0, Python 3.11.9
# 0.1.0 - Caiman v1.10.4 (1.10.0 is major version upgrade), Mesmerize-core 0.3.0, Mesmerize-viz 0.1.0b1, Python 3.11.8
# 0.0.3 - Initial working version. Caiman 1.9.16, mesmerize-core 0.3.0, mesmerize-viz 0.1.0b1, Python 3.11.7

# Run with:
# docker run --rm -it wanglabneuro/mesmerize-base:0.1.2 /bin/bash