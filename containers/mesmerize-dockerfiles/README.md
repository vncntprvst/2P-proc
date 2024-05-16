## Docker files for Mesmerize / Caiman
This Docker file creates an image that runs Mesmerize / CaImAn

### Usage  
  With **Docker**
    
  Run the container:
  ```bash
  docker run -it --rm --gpus all --name mescore -v \Your\Data\Folder:/src/data/folder wanglabneuro/mesmerize-base
  ```
  If running as current user, add the `-u $(id -u):$(id -g)` flag to the command above.
  If you want to run the container in the background, add the `-d` flag.
  ```bash
  docker run -u $(id -u):$(id -g) --rm -d --gpus all --name mescore -v \Your\Data\Folder:/src/data/folder wanglabneuro/mesmerize-base
  ```
  ```
  The `-it` and `--rm` flags can be changed or ignored. See [documentation](https://docs.docker.com/engine/reference/commandline/run/). 
  Keep the `--gpus all` flag to provide access to the GPU.

  With **Singularity**  
  Build the image: `singularity build dannce-base.simg docker://wanglabneuro/mesmerize-base:latest`.    


###  Updates
  To update the image, edit the Docker file, then run `build.sh`.  
  If you have access to the Wang lab's Dockerhub, push the new image with `push.sh`. Otherwise, make a commit or a PR to this repo and ask an admin to do it. 




