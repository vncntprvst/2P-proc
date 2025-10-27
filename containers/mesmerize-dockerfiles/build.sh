#!/bin/bash

docker build -t wanglabneuro/mesmerize-base:latest -t wanglabneuro/mesmerize-base:0.2.1 -f Dockerfile context

# Scan the image for vulnerabilities
if ! command -v trivy &> /dev/null
then
    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image --severity HIGH,CRITICAL --skip-files compiler.js --scanners vuln wanglabneuro/mesmerize-base:latest
else
    trivy image --severity HIGH,CRITICAL --skip-files compiler.js --scanners vuln wanglabneuro/mesmerize-base:latest
fi

# Versions:
# 0.2.1 - Caiman v1.12.2, Mesmerize-core 0.5.0, Mesmerize-viz 0.1.0, Python 3.10.18 (reverted to Python 3.10 in case people want to use TensorFlow)
# 0.1.2 - Caiman v1.11.1, Mesmerize-core 0.4.0, Mesmerize-viz 0.1.0, Python 3.11.9
# 0.1.1 - Caiman v1.11.0, Mesmerize-core 0.4.0, Mesmerize-viz 0.1.0, Python 3.11.9
# 0.1.0 - Caiman v1.10.4 (1.10.0 is major version upgrade), Mesmerize-core 0.3.0, Mesmerize-viz 0.1.0b1, Python 3.11.8
# 0.0.3 - Initial working version. Caiman 1.9.16, mesmerize-core 0.3.0, mesmerize-viz 0.1.0b1, Python 3.11.7

# Run with:
# docker run --rm -it wanglabneuro/mesmerize-base:0.2.1 /bin/bash
# check caiman version: docker run --rm -it wanglabneuro/mesmerize-base:0.2.1 python --version && python -c "import caiman; print(caiman.__version__)"
# check mesmerize-core version: docker run --rm -it wanglabneuro/mesmerize-base:0.2.1 python -c "import mesmerize_core; print(mesmerize_core.__version__)"
