# GitHub Copilot Instructions for Analysis 2P

## Repository Overview

Analysis 2P is a comprehensive pipeline for processing and analyzing 2-photon calcium imaging data alongside behavioral analysis. This multi-language repository integrates Python and MATLAB components with several established computational neuroscience tools.

## Codebase Architecture

### Primary Components

1. **Data Processing Pipeline (Python)**
   - Uses CaImAn and Mesmerize for motion correction, ROI extraction, and spike deconvolution
   - Main entry point: `Mesmerize/batch_mcorr_cnmf.py`
   - Configuration files: `Mesmerize/parameters/*.json` and `Mesmerize/paths/*.json`

2. **Post-Processing Pipeline (MATLAB)**
   - Behavior analysis with DeepLabCut integration
   - Rastermap clustering for neuronal activity
   - Multi-session registration capabilities
   - Main scripts in `Matlab/` directory

3. **Container Management**
   - Docker/Singularity configurations in `containers/`
   - Environment setup scripts for various tools

## Key Technologies and Dependencies

### Python Stack
- **CaImAn**: Motion correction, source extraction, spike deconvolution
- **Mesmerize-Core**: Parameter comparison and workflow management
- **Suite2p**: Alternative ROI extraction pipeline
- **DeepLabCut**: Behavior analysis and keypoint tracking
- **Rastermap**: Neuronal activity clustering

### MATLAB Components
- Custom analysis scripts for 2P data processing
- Integration with Python tools via system calls
- Behavior analysis and correlation studies

### Environment Management
- `mescore` conda environment for primary Python pipeline
- Separate environments for specialized tools (suite2p, rastermap, deeplabcut)
- Container support for cluster computing

## Code Style and Conventions

### Python Code
- Follow PEP 8 styling conventions
- Use descriptive variable names reflecting neuroscience terminology
- Prefer numpy arrays for imaging data manipulation
- Use pathlib.Path for file system operations
- Include comprehensive docstrings for functions

### MATLAB Code
- Use camelCase for function names
- Include detailed comments for complex analysis steps
- Use cell arrays for flexible data structures
- Follow MATLAB best practices for vectorization

### Configuration Files
- Use JSON format for parameter files
- Include comprehensive documentation in parameter templates
- Maintain separate configs for different data types/scales

## Domain-Specific Context

### 2-Photon Imaging Terminology
- **ROI**: Region of Interest (individual neurons)
- **F/ΔF**: Fluorescence change relative to baseline
- **Deconvolution**: Spike inference from calcium signals
- **Motion correction**: Alignment of video frames
- **CNMF**: Constrained Non-negative Matrix Factorization

### Data Processing Workflow
1. Motion correction (rigid/non-rigid)
2. ROI extraction and spatial component identification
3. Temporal component extraction
4. Spike deconvolution
5. Quality assessment and component filtering
6. Behavioral correlation analysis

### Common Parameters
- `fr`: Frame rate (Hz)
- `gSig`: Expected neuron radius (pixels)
- `K`: Number of components to extract
- `p`: Order of autoregressive model for spike inference
- `merge_thr`: Threshold for component merging

## File Organization Patterns

### Data Paths
- Raw data typically in TIFF format
- Processed outputs in HDF5 or MAT format
- Parameter files use JSON format
- Batch processing uses path configuration files

### Naming Conventions
- Use descriptive prefixes: `params_`, `paths_`, `batch_`
- Include data scale indicators: `_small`, `_test`
- Version parameters appropriately: `_v1`, `_v2`

## Common Tasks and Patterns

### Parameter Optimization
- Use Mesmerize notebooks for systematic parameter exploration
- Create template parameter files for different experimental conditions
- Document parameter choices and their effects

### Batch Processing
- Group related datasets for efficient processing
- Handle memory management for large datasets
- Implement proper error handling and logging

### Multi-Session Analysis
- Use CaImAn's registration algorithms for cross-session alignment
- Maintain consistent ROI identification across sessions
- Handle variations in field of view and imaging conditions

### Behavior Integration
- Synchronize imaging and behavior data timestamps
- Extract relevant behavioral events (wipes, movements)
- Correlate neural activity with behavioral states

## Error Handling and Debugging

### Common Issues
- Memory limitations with large datasets
- Parameter sensitivity in ROI extraction
- File path and environment configuration problems
- Cross-platform compatibility (Windows/Linux/Mac)

### Best Practices
- Implement comprehensive logging
- Use try-catch blocks for file operations
- Validate input parameters before processing
- Provide informative error messages with suggested solutions

## Testing and Validation

### Test Data
- Use small test datasets for rapid iteration
- Validate pipeline outputs against known ground truth
- Compare results across different parameter settings

### Quality Checks
- Visual inspection of motion correction results
- ROI quality assessment (shape, activity patterns)
- Spike deconvolution validation
- Cross-validation of behavioral correlations

## Cluster Computing Considerations

### Resource Management
- Memory requirements scale with data size and parameters
- Use appropriate SLURM directives for job submission
- Handle temporary file cleanup

### Environment Isolation
- Use containers or conda environments for reproducibility
- Manage module loading for cluster-specific software
- Handle GPU requirements when available

## Documentation Standards

### Code Comments
- Explain complex algorithmic steps
- Document parameter choices and their rationale
- Include references to relevant literature
- Provide usage examples for key functions

### Configuration Files
- Include comprehensive parameter descriptions
- Provide recommended ranges for key parameters
- Document dependencies between parameters
- Include example configurations for common use cases

## Integration Points

When suggesting code changes or new features:

1. **Respect the multi-tool architecture** - maintain compatibility with CaImAn, Suite2p, DeepLabCut, etc.
2. **Consider computational requirements** - suggest memory-efficient approaches for large datasets
3. **Maintain scientific rigor** - ensure suggestions align with computational neuroscience best practices
4. **Preserve flexibility** - support different experimental paradigms and data scales
5. **Document thoroughly** - include clear explanations for complex analysis steps

## Version Control Considerations

- This repository integrates multiple external tools that evolve independently
- Parameter files should be versioned alongside code changes
- Container configurations should be maintained for reproducibility
- Changes should be tested across different scales of data (small test sets to full experiments)
