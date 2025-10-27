# Suite2p Docker Image

Get version:

```bash
docker run --rm -it wanglabneuro/suite2p_rastermap python -m suite2p --version
> suite2p v0.14.5.dev8+gfd75275
```

Get help:

```bash
docker run --rm -it wanglabneuro/suite2p_rastermap python -m suite2p -h
> usage: __main__.py [-h] [--single_plane] [--ops OPS] [--db DB] [--version] [--suite2p_version SUITE2P_VERSION] [--look_one_level_down LOOK_ONE_LEVEL_DOWN] [--fast_disk FAST_DISK]
                   [--delete_bin DELETE_BIN] [--mesoscan MESOSCAN] [--bruker BRUKER] [--bruker_bidirectional BRUKER_BIDIRECTIONAL] [--h5py H5PY] [--h5py_key H5PY_KEY]
                   [--nwb_file NWB_FILE] [--nwb_driver NWB_DRIVER] [--nwb_series NWB_SERIES] [--save_path0 SAVE_PATH0] [--save_folder SAVE_FOLDER] [--subfolders SUBFOLDERS]
                   [--move_bin MOVE_BIN] [--nplanes NPLANES] [--nchannels NCHANNELS] [--functional_chan FUNCTIONAL_CHAN] [--tau TAU] [--fs FS] [--force_sktiff FORCE_SKTIFF]
                   [--frames_include FRAMES_INCLUDE] [--multiplane_parallel MULTIPLANE_PARALLEL] [--ignore_flyback IGNORE_FLYBACK] [--preclassify PRECLASSIFY] [--save_mat SAVE_MAT]
                   [--save_NWB SAVE_NWB] [--combined COMBINED] [--aspect ASPECT] [--do_bidiphase DO_BIDIPHASE] [--bidiphase BIDIPHASE] [--bidi_corrected BIDI_CORRECTED]
                   [--do_registration DO_REGISTRATION] [--two_step_registration TWO_STEP_REGISTRATION] [--keep_movie_raw KEEP_MOVIE_RAW] [--nimg_init NIMG_INIT] [--batch_size BATCH_SIZE]
                   [--maxregshift MAXREGSHIFT] [--align_by_chan ALIGN_BY_CHAN] [--reg_tif REG_TIF] [--reg_tif_chan2 REG_TIF_CHAN2] [--subpixel SUBPIXEL]
                   [--smooth_sigma_time SMOOTH_SIGMA_TIME] [--smooth_sigma SMOOTH_SIGMA] [--th_badframes TH_BADFRAMES] [--norm_frames NORM_FRAMES] [--force_refImg FORCE_REFIMG]
                   [--pad_fft PAD_FFT] [--nonrigid NONRIGID] [--block_size BLOCK_SIZE [BLOCK_SIZE ...]] [--snr_thresh SNR_THRESH] [--maxregshiftNR MAXREGSHIFTNR] [--1Preg 1PREG]
                   [--spatial_hp_reg SPATIAL_HP_REG] [--pre_smooth PRE_SMOOTH] [--spatial_taper SPATIAL_TAPER] [--roidetect ROIDETECT] [--spikedetect SPIKEDETECT]
                   [--sparse_mode SPARSE_MODE] [--spatial_scale SPATIAL_SCALE] [--connected CONNECTED] [--nbinned NBINNED] [--max_iterations MAX_ITERATIONS]
                   [--threshold_scaling THRESHOLD_SCALING] [--max_overlap MAX_OVERLAP] [--high_pass HIGH_PASS] [--spatial_hp_detect SPATIAL_HP_DETECT] [--denoise DENOISE]
                   [--anatomical_only ANATOMICAL_ONLY] [--diameter DIAMETER] [--cellprob_threshold CELLPROB_THRESHOLD] [--flow_threshold FLOW_THRESHOLD] [--spatial_hp_cp SPATIAL_HP_CP]
                   [--pretrained_model PRETRAINED_MODEL] [--soma_crop SOMA_CROP] [--neuropil_extract NEUROPIL_EXTRACT] [--inner_neuropil_radius INNER_NEUROPIL_RADIUS]
                   [--min_neuropil_pixels MIN_NEUROPIL_PIXELS] [--lam_percentile LAM_PERCENTILE] [--allow_overlap ALLOW_OVERLAP] [--use_builtin_classifier USE_BUILTIN_CLASSIFIER]
                   [--classifier_path CLASSIFIER_PATH] [--chan2_thres CHAN2_THRES] [--baseline BASELINE] [--win_baseline WIN_BASELINE] [--sig_baseline SIG_BASELINE]
                   [--prctile_baseline PRCTILE_BASELINE] [--neucoeff NEUCOEFF]

Suite2p parameters

optional arguments:
  -h, --help            show this help message and exit
  --single_plane        run single plane ops
  --ops OPS             options
  --db DB               options
  --version             print version number.
  --suite2p_version SUITE2P_VERSION
                        suite2p_version : 0.14.5.dev8+gfd75275
  --look_one_level_down LOOK_ONE_LEVEL_DOWN
                        look_one_level_down : False
  --fast_disk FAST_DISK
                        fast_disk : []
  --delete_bin DELETE_BIN
                        delete_bin : False
  --mesoscan MESOSCAN   mesoscan : False
  --bruker BRUKER       bruker : False
  --bruker_bidirectional BRUKER_BIDIRECTIONAL
                        bruker_bidirectional : False
  --h5py H5PY           h5py : []
  --h5py_key H5PY_KEY   h5py_key : data
  --nwb_file NWB_FILE   nwb_file :
  --nwb_driver NWB_DRIVER
                        nwb_driver :
  --nwb_series NWB_SERIES
                        nwb_series :
  --save_path0 SAVE_PATH0
                        save_path0 :
  --save_folder SAVE_FOLDER
                        save_folder : []
  --subfolders SUBFOLDERS
                        subfolders : []
  --move_bin MOVE_BIN   move_bin : False
  --nplanes NPLANES     nplanes : 1
  --nchannels NCHANNELS
                        nchannels : 1
  --functional_chan FUNCTIONAL_CHAN
                        functional_chan : 1
  --tau TAU             tau : 1.0
  --fs FS               fs : 10.0
  --force_sktiff FORCE_SKTIFF
                        force_sktiff : False
  --frames_include FRAMES_INCLUDE
                        frames_include : -1
  --multiplane_parallel MULTIPLANE_PARALLEL
                        multiplane_parallel : False
  --ignore_flyback IGNORE_FLYBACK
                        ignore_flyback : []
  --preclassify PRECLASSIFY
                        preclassify : 0.0
  --save_mat SAVE_MAT   save_mat : False
  --save_NWB SAVE_NWB   save_NWB : False
  --combined COMBINED   combined : True
  --aspect ASPECT       aspect : 1.0
  --do_bidiphase DO_BIDIPHASE
                        do_bidiphase : False
  --bidiphase BIDIPHASE
                        bidiphase : 0
  --bidi_corrected BIDI_CORRECTED
                        bidi_corrected : False
  --do_registration DO_REGISTRATION
                        do_registration : True
  --two_step_registration TWO_STEP_REGISTRATION
                        two_step_registration : False
  --keep_movie_raw KEEP_MOVIE_RAW
                        keep_movie_raw : False
  --nimg_init NIMG_INIT
                        nimg_init : 300
  --batch_size BATCH_SIZE
                        batch_size : 500
  --maxregshift MAXREGSHIFT
                        maxregshift : 0.1
  --align_by_chan ALIGN_BY_CHAN
                        align_by_chan : 1
  --reg_tif REG_TIF     reg_tif : False
  --reg_tif_chan2 REG_TIF_CHAN2
                        reg_tif_chan2 : False
  --subpixel SUBPIXEL   subpixel : 10
  --smooth_sigma_time SMOOTH_SIGMA_TIME
                        smooth_sigma_time : 0
  --smooth_sigma SMOOTH_SIGMA
                        smooth_sigma : 1.15
  --th_badframes TH_BADFRAMES
                        th_badframes : 1.0
  --norm_frames NORM_FRAMES
                        norm_frames : True
  --force_refImg FORCE_REFIMG
                        force_refImg : False
  --pad_fft PAD_FFT     pad_fft : False
  --nonrigid NONRIGID   nonrigid : True
  --block_size BLOCK_SIZE [BLOCK_SIZE ...]
                        block_size : [128, 128]
  --snr_thresh SNR_THRESH
                        snr_thresh : 1.2
  --maxregshiftNR MAXREGSHIFTNR
                        maxregshiftNR : 5
  --1Preg 1PREG         1Preg : False
  --spatial_hp_reg SPATIAL_HP_REG
                        spatial_hp_reg : 42
  --pre_smooth PRE_SMOOTH
                        pre_smooth : 0
  --spatial_taper SPATIAL_TAPER
                        spatial_taper : 40
  --roidetect ROIDETECT
                        roidetect : True
  --spikedetect SPIKEDETECT
                        spikedetect : True
  --sparse_mode SPARSE_MODE
                        sparse_mode : True
  --spatial_scale SPATIAL_SCALE
                        spatial_scale : 0
  --connected CONNECTED
                        connected : True
  --nbinned NBINNED     nbinned : 5000
  --max_iterations MAX_ITERATIONS
                        max_iterations : 20
  --threshold_scaling THRESHOLD_SCALING
                        threshold_scaling : 1.0
  --max_overlap MAX_OVERLAP
                        max_overlap : 0.75
  --high_pass HIGH_PASS
                        high_pass : 100
  --spatial_hp_detect SPATIAL_HP_DETECT
                        spatial_hp_detect : 25
  --denoise DENOISE     denoise : False
  --anatomical_only ANATOMICAL_ONLY
                        anatomical_only : 0
  --diameter DIAMETER   diameter : 0
  --cellprob_threshold CELLPROB_THRESHOLD
                        cellprob_threshold : 0.0
  --flow_threshold FLOW_THRESHOLD
                        flow_threshold : 1.5
  --spatial_hp_cp SPATIAL_HP_CP
                        spatial_hp_cp : 0
  --pretrained_model PRETRAINED_MODEL
                        pretrained_model : cyto
  --soma_crop SOMA_CROP
                        soma_crop : True
  --neuropil_extract NEUROPIL_EXTRACT
                        neuropil_extract : True
  --inner_neuropil_radius INNER_NEUROPIL_RADIUS
                        inner_neuropil_radius : 2
  --min_neuropil_pixels MIN_NEUROPIL_PIXELS
                        min_neuropil_pixels : 350
  --lam_percentile LAM_PERCENTILE
                        lam_percentile : 50.0
  --allow_overlap ALLOW_OVERLAP
                        allow_overlap : False
  --use_builtin_classifier USE_BUILTIN_CLASSIFIER
                        use_builtin_classifier : False
  --classifier_path CLASSIFIER_PATH
                        classifier_path :
  --chan2_thres CHAN2_THRES
                        chan2_thres : 0.65
  --baseline BASELINE   baseline : maximin
  --win_baseline WIN_BASELINE
                        win_baseline : 60.0
  --sig_baseline SIG_BASELINE
                        sig_baseline : 10.0
  --prctile_baseline PRCTILE_BASELINE
                        prctile_baseline : 8.0
  --neucoeff NEUCOEFF   neucoeff : 0.7
  ```
