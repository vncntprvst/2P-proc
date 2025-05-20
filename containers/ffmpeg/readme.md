### Download the ffmpeg container from Docker Hub
Load Apptainer: `$ module load openmind8/apptainer/1.1.7`.  
Then run the following command to download the ffmpeg container from Docker Hub:
```bash
apptainer build <path_to_image>ffmpeg.sif docker://jrottenberg/ffmpeg:latest
```

### Run the ffmpeg container
```bash
apptainer exec -B <data_path>:/data ffmpeg.sif \
  ffmpeg -y -i /data/Movie_2P.avi -vcodec libx264 /data/Movie_2P.mp4
```