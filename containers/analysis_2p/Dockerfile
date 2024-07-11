FROM wanglabneuro/mesmerize-base:latest

USER root

# Create $IM_USER user with UID=1000 and add it to the 'users' group
ARG IM_USER=a2P_user                                    # user name
ARG NB_UID=1001                                         # user id (user 1000 is jovyan)
RUN useradd -m -s /bin/bash -N -u $NB_UID $IM_USER      # create user
RUN GID=$(getent group users | cut -d: -f3) && \                
    usermod -a -G $GID $IM_USER                         # add user to group 'users'

RUN fix-permissions /home/$IM_USER

# RUN fix-permissions /etc/ld.so.cache

# Create code directory in user home
RUN mkdir -p /code && \
    mkdir -p /data

# Set permissions for $IM_USER
RUN chown -R $IM_USER:users /code && \
    chown -R $IM_USER:users /data

# Give IM_USER read and write permissions to all files in /home/$NB_USER
RUN chown -R $IM_USER:users /home/$NB_USER && \
    chmod -R u+rw /home/$NB_USER

# Set working directory to Mesmerize code directory
COPY Mesmerize /code/Mesmerize
COPY requirements.txt /code/Mesmerize/requirements.txt
WORKDIR /code/Mesmerize

# # Activate mescore environment by default
# SHELL [ "/bin/bash", "--login",  "-c" ]
# ENV PATH $CONDA_DIR/envs/mescore/bin:$PATH
# RUN echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /root/.profile && \
#     conda init bash && conda activate mescore && \
#     echo "conda activate mescore" >> ~/.bashrc

# Install additional Analysis 2P dependencies via pip 
SHELL ["conda","run","-n","mescore","/bin/bash","-c"]
# RUN conda install -c conda-forge mkl mkl_fft -y
RUN pip install -r requirements.txt

USER $IM_USER
# RUN conda update caiman -c conda-forge
# RUN caimanmanager install
# Copy caiman_data to user home, just to keep it separate from jovyan
RUN cp -r /home/$NB_USER/caiman_data /home/$IM_USER && \
    chown -R $IM_USER:users /home/$IM_USER/caiman_data && \
    chmod -R 777 /home/$IM_USER/caiman_data/temp

# Set CAIMAN_DATA environment variable
ENV CAIMAN_DATA=/home/$IM_USER/caiman_data
# Set $CAIMAN_TEMP
ENV CAIMAN_TEMP=/home/$IM_USER/caiman_data/temp
# These environment variables can be overridden by the user when running the container: 
# docker run -e CAIMAN_DATA=/path/to/caiman_data -e CAIMAN_TEMP=/path/to/caiman_temp ...
# apptainer run -e CAIMAN_DATA=/path/to/caiman_data -e CAIMAN_TEMP=/path/to/caiman_temp ...

# Initialize conda for IM_USER
RUN echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /home/$IM_USER/.profile

# start batch script to run Mesmerize analysis pipeline on batch of files when container is run
# ENTRYPOINT ["conda", "run", "-n", "mescore", "python", "-u", "batch_mcorr_cnmf.py"]