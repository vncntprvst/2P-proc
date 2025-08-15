FROM continuumio/miniconda3:23.9.0-0

ARG DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set the environment variables
ENV CONDA_DIR=/opt/conda
ENV PATH=$CONDA_DIR/bin:$PATH
# RUN conda update conda 
    # && \
    # conda install conda-build

# Make conda activate command available from /bin/bash --login shells
RUN echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /root/.profile 
# Make conda activate command available from /bin/bash --interactive shells
RUN conda init bash

# Create the suite2p conda environment with Python 3.9
RUN conda create --name suite2p python=3.9 -y

# Make RUN commands use the Suite2p environment
SHELL ["conda", "run", "-n", "suite2p", "/bin/bash", "-c"]
RUN conda install --quiet --yes ipykernel && \
    python -m ipykernel install --user --name suite2p --display-name "Suite2p"

# Create a working directory
RUN mkdir -p /app
WORKDIR /app

# Install suite2p
# RUN python -m pip install suite2p[io]
RUN git clone https://github.com/MouseLand/suite2p.git && \
    cd suite2p && \
    python -m pip install .

# Copy the requirements file
# COPY requirements.txt .

# Install Python dependencies
# RUN pip install --no-cache-dir -r requirements.txt

# Copy the scripts
RUN mkdir -p /app/scripts
WORKDIR /app/scripts
COPY scripts/* .

# Set Suite2p as default environment
SHELL [ "/bin/bash", "--login",  "-c" ]
ENV PATH="$CONDA_DIR/envs/suite2p/bin:$PATH"
RUN echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /root/.profile && \
    conda init bash && conda activate suite2p && \
    echo "conda activate suite2p" >> ~/.bashrc

# Set the entry point
# ENTRYPOINT ["python", "-m", "suite2p"]