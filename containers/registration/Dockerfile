# Cross-session cell registration (pipeline.register_sessions, ROICaT method).
# ROICaT needs Python >= 3.11 and PyTorch, so it lives apart from the 2p_proc image
# (Python 3.10, CaImAn 1.12.2). The caiman method stays in the 2p_proc image.
FROM python:3.11-slim

# OpenCV and libtiff runtime libraries; Tk (ROICaT imports Matplotlib's TkAgg backend);
# compiler and libtiff headers to build pylibtiff (optimouse dependency, no wheel for this Python)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libtiff6 libtiff-dev tk build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# CPU builds of the torch / torchvision versions roicat pins (cluster nodes have no GPU;
# avoids several GB of CUDA libraries)
RUN uv pip install --system --no-cache --index-url https://download.pytorch.org/whl/cpu \
        torch==2.14.1 torchvision==0.29.1

# optimouse (pinned: bump together with the image tag in build_docker_singularity.sh) and ROICaT.
# opencv-python (optimouse) and opencv-contrib-python-headless (romatch-roicat) both install the
# cv2 folder, and whichever is written last wins. Only the contrib build has
# cv2.optflow.createOptFlow_DeepFlow, ROICaT's default nonrigid alignment, so it is reinstalled last.
RUN uv pip install --system --no-cache optimouse==0.1.11 "roicat[all]==1.7.12" \
        "opencv-python<5" "opencv-contrib-python-headless<5" && \
    uv pip install --system --no-cache --reinstall "opencv-contrib-python-headless<5"

ENV MPLBACKEND=Agg \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=UTF-8

# Fail the build if the registration entry point cannot load or DeepFlow is missing
RUN python -c "import cv2, roicat, modules.cell_registration, pipeline.register_sessions; cv2.optflow.createOptFlow_DeepFlow(); print('roicat', roicat.__version__, 'opencv', cv2.__version__)"

# Test: docker run --rm wanglabneuro/2p_registration:latest python -m pipeline.register_sessions --help
