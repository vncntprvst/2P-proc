FROM wanglabneuro/mesmerize-base:latest

LABEL description="AIND non-rigid motion correction capsule using CaImAn/NoRMCorre"
LABEL version="1.0"

# Install aind-data-schema and CaImAn
RUN uv pip install aind-data-schema && \
    uv pip install "git+https://github.com/flatironinstitute/CaImAn.git@v1.12.2" && \
    caimanmanager install

# Install optimouse from PyPI (provides shared pipeline utilities if needed)
RUN uv pip install optimouse

# Copy capsule code
COPY code/ /code/

WORKDIR /code

# Prebuild Matplotlib font cache
ENV MPLCONFIGDIR=/root/.config/matplotlib
RUN mkdir -p "$MPLCONFIGDIR" && \
    python - <<'PY'
import matplotlib as mpl
mpl.use('Agg')
from matplotlib import font_manager
_ = font_manager.fontManager.ttflist
print('Prebuilt Matplotlib font cache at:', mpl.get_configdir())
PY

# CaImAn environment variables
ENV CAIMAN_DATA=/root/caiman_data
ENV CAIMAN_TEMP=/root/caiman_data/temp

# UTF-8 locale
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUTF8=1

# Test: docker run --rm wanglabneuro/aind-nonrigid-mcorr python -c "import caiman; print(caiman.__version__)"
