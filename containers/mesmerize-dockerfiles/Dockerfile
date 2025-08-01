FROM python:3.10-slim-bookworm

# Update the base image
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ cmake build-essential \
    libgl1 libgl1-mesa-glx libegl1-mesa mesa-vulkan-drivers \
    libarchive13 x11-apps curl git \
    libglib2.0-0 libsm6 libxext6 libxrender-dev \
    libtiff-dev libhdf5-dev \
    libjpeg-dev libpng-dev zlib1g-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 
WORKDIR /home
RUN mkdir -p code
WORKDIR /home/code
COPY packages/uv_setup.sh /home/code/uv_setup.sh
RUN chmod +x /home/code/uv_setup.sh

# Install caiman environment
ENV KERAS_BACKEND=tensorflow
ENV TF_CPP_MIN_LOG_LEVEL=2
ENV CUDA_VISIBLE_DEVICES=0
RUN /bin/bash /home/code/uv_setup.sh

# copy fix-permissions script from jupyter/base-notebook
COPY --from=jupyter/base-notebook /usr/local/bin/fix-permissions /usr/local/bin/fix-permissions
RUN chmod a+rx /usr/local/bin/fix-permissions

# Clean up
RUN rm -rf /home/code/uv_setup.sh

# Activate mescore environment by default
ENV PATH="/home/code/mescore/bin:$PATH"
RUN echo "source /root/.local/bin/env" >> /root/.profile
RUN echo "source /home/code/mescore/bin/activate" >> /root/.profile
SHELL [ "/bin/bash", "--login", "-c" ]
RUN echo "source /root/.local/bin/env" >> ~/.bashrc
RUN echo "source /home/code/mescore/bin/activate" >> ~/.bashrc
