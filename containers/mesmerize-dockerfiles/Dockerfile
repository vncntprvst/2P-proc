FROM tensorflow/tensorflow:2.14.0-gpu-jupyter
# FROM tensorflow/tensorflow:latest-gpu
#  TensorFlow >= 2.15.0 requires CUDA 12.2, which isn't convenient for now
#  See https://www.tensorflow.org/install/source#gpu

LABEL maintainer="Vincent Prevosto <prevosto@mit.edu>"

USER root

ENV DEBIAN_FRONTEND=noninteractive

# Install system packages
RUN apt update && \
    apt install -y --no-install-recommends \
    mesa-vulkan-drivers \
    libgl1-mesa-glx \
    libegl1-mesa \
    libgl1-mesa-dev \
    libarchive13 \
    x11-apps \
    git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
    
# Create $NB_USER user with UID=1000 and in the 'users' group, if it does not exist
ARG NB_USER="jovyan"
ARG NB_UID="1000"
# RUN useradd -m -s /bin/bash -N -u $NB_UID $NB_USER || true
# RUN GID=$(getent group users | cut -d: -f3) && \
#     usermod -a -G $GID $NB_USER
ARG NB_GID="100"

# Configure environment
ENV CONDA_DIR=/opt/conda \
    SHELL=/bin/bash \
    NB_USER="${NB_USER}" \
    NB_UID=${NB_UID} \
    NB_GID=${NB_GID} \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    LANGUAGE=C.UTF-8
ENV PATH="${CONDA_DIR}/bin:${PATH}" \
    HOME="/home/${NB_USER}"

RUN useradd --no-log-init --create-home --shell /bin/bash --uid "${NB_UID}" --no-user-group "${NB_USER}"

# Install Miniconda
ENV PYTHON_VERSION=311
ENV MINICONDA_VERSION=24.3.0-0
ENV LATEST_CONDA_SCRIPT="Miniconda3-py${PYTHON_VERSION}_${MINICONDA_VERSION}-Linux-x86_64.sh"
RUN curl -sSL https://repo.anaconda.com/miniconda/$LATEST_CONDA_SCRIPT -o ~/miniconda.sh && \
    chmod +x ~/miniconda.sh && \
    ~/miniconda.sh -b -p ${CONDA_DIR} && \
    rm ~/miniconda.sh
RUN conda clean -tipy && \
    conda update -y conda

# Make conda activate command available from /bin/bash --login shells
RUN echo ". ${CONDA_DIR}/etc/profile.d/conda.sh" >> /root/.profile 
# Make conda activate command available from /bin/bash --interactive shells
RUN conda init bash

# copy fix-permissions script from jupyter/base-notebook
COPY --from=jupyter/base-notebook /usr/local/bin/fix-permissions /usr/local/bin/fix-permissions
RUN chmod a+rx /usr/local/bin/fix-permissions

# RUN echo "auth requisite pam_deny.so" >> /etc/pam.d/su && \
#     sed -i.bak -e 's/^%admin/#%admin/' /etc/sudoers && \
#     sed -i.bak -e 's/^%sudo/#%sudo/' /etc/sudoers && \
#  && \
RUN chown "${NB_USER}:${NB_GID}" "${CONDA_DIR}" && \
    chmod g+w /etc/passwd
RUN find ${CONDA_DIR} -type l -xtype l -delete && \
    find /home/${NB_USER} -type l -xtype l -delete && \
    fix-permissions ${CONDA_DIR} && \
    fix-permissions /home/${NB_USER}

# RUN mkdir -p /home/$NB_USER
# RUN fix-permissions $CONDA_DIR
# RUN fix-permissions /home/$NB_USER

#Switch to user
USER $NB_UID

# Copy environment installation files
COPY packages/mesmerize_env.yml packages/mesmerize_env.yml
COPY packages/mesmerize_requirements.txt packages/mesmerize_requirements.txt

# Install environment
RUN conda install -y -c conda-forge mamba
RUN mamba create -n mescore -c conda-forge mesmerize-core && \
    conda clean -tipy
RUN mamba env update -n mescore -f packages/mesmerize_env.yml

# Add kernel to Jupyter
SHELL ["conda","run","-n","mescore","/bin/bash","-c"]
RUN python -m ipykernel install --user --name mescore --display-name "Python (mescore)"
# ENV LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH
# install caimanmanager
RUN caimanmanager install 
# Install packages from pip
RUN pip install -r packages/mesmerize_requirements.txt
# If modified code file exists, re-install caiman with it
# Copy modified code file to temp directory
COPY code_updates/estimates.py /tmp/estimates.py
WORKDIR /home/$NB_USER
RUN mkdir -p code && cd code && \
    git clone --recursive https://github.com/nel-lab/mesmerize-core.git && \
    git clone --recursive https://github.com/kushalkolar/fastplotlib.git && \
    git clone --recursive https://github.com/flatironinstitute/CaImAn.git 

    # --branch v1.9.16 && \
    # cd CaImAn && \
    # git checkout -b wanglab
# RUN if [ -e "/tmp/estimates.py" ]; then \
#         echo "Updating CaImAn with modified code" && \
#         cd code/CaImAn && \
#         cp /tmp/estimates.py caiman/source_extraction/cnmf/estimates.py -f && \
#         pip install -e . && \
#         conda clean --all -y ; \
#     fi

# Switch to default bash shell
SHELL ["/bin/bash", "--login", "-c"]

WORKDIR /home/$NB_USER/code/CaImAn
RUN git stash && \
    git checkout main && \
    git pull origin main

# Update CaImAn in mescore environment
RUN mamba update -y -n mescore -c conda-forge caiman

# Activate mescore environment by default
USER root
RUN echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /etc/profile.d/conda.sh
SHELL [ "/bin/bash", "--login",  "-c" ]
ENV PATH $CONDA_DIR/envs/mescore/bin:$PATH
RUN echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /root/.profile && \
    conda init bash && conda activate mescore && \
    echo "conda activate mescore" >> ~/.bashrc

# Switch to mescore environment
SHELL ["conda","run","-n","mescore","/bin/bash","-c"]

# #Switch to user
USER $NB_UID
# USER root
ENTRYPOINT []