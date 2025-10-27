"""Plotting functions for visualizing zone patterns and labeled zones.

Example usage:
plot_labeled_and_zone_patterns(labeled_zones, zone_pattern, export_path='/home/wanglab/data/2P/Analysis/Scnn1aAi14_B2M0/04222024/run1run2/test_modules')

"""

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

def plot_zone_pattern(zone_pattern, zone_pattern_contig, export_path=None):
    """
    Create visualization of the patch zones and their continuity.
    
    Parameters:
    -----------
    zone_pattern : numpy.ndarray
        2D array containing the zone pattern with non-contiguous unique zone IDs
    zone_pattern_contig : numpy.ndarray
        2D array containing the zone pattern with continuous zone IDs
    export_path : str or pathlib.Path, optional
        Path where to save the figure. If None, figure will be displayed but not saved.
    
    Returns:
    --------
    fig : matplotlib.figure.Figure
        The figure object containing the plots
    """
    # Create figure with two subplots
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    
    # Plot original zone pattern
    unique_zones = len(np.unique(zone_pattern)) - 1  # Subtract 1 for background (0)
    cmap = plt.cm.get_cmap('plasma', unique_zones)
    im0 = axes[0].imshow(zone_pattern, cmap=cmap)
    axes[0].set_title(f'Original Zone Pattern\n({unique_zones} unique zones)')
    axes[0].set_xticks([])
    axes[0].set_yticks([])
    
    # Plot continuous zone pattern
    unique_contig = len(np.unique(zone_pattern_contig)) - 1  # Subtract 1 for background (0)
    cmap = plt.cm.get_cmap('viridis', unique_contig)
    im1 = axes[1].imshow(zone_pattern_contig, cmap=cmap)
    axes[1].set_title(f'Continuous Zone Pattern\n({unique_contig} zones)')
    axes[1].set_xticks([])
    axes[1].set_yticks([])
    
    # Add colorbars
    cbar0 = fig.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.04)
    cbar0.set_label('Zone ID (non-contiguous)')
    cbar1 = fig.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.04)
    cbar1.set_label('Zone ID (contiguous)')
    
    plt.tight_layout()
    
    # Save figure if export_path is provided
    if export_path is not None:
        # Convert string path to Path object if needed
        export_path = Path(export_path)
        
        # Ensure plot directory exists
        plot_dir = export_path / 'plots'
        plot_dir.mkdir(parents=True, exist_ok=True)
        
        # Save the figure
        fig_path = plot_dir / 'zone_patterns.png'
        fig.savefig(fig_path, dpi=150, bbox_inches='tight')
        print(f"Zone pattern figure saved to {fig_path}")
    
    return fig

def plot_labeled_and_zone_patterns(labeled_zones, zone_pattern, export_path=None):
    """
    Plot labeled_zones and zone_pattern side by side for comparison.

    Parameters:
    -----------
    labeled_zones : numpy.ndarray
        2D array containing the labeled zones.
    zone_pattern : numpy.ndarray
        2D array containing the zone pattern.
    export_path : str or pathlib.Path, optional
        Path where to save the figure. If None, the figure will be displayed but not saved.

    Returns:
    --------
    fig : matplotlib.figure.Figure
        The figure object containing the plots.
    """
    # Create figure with two subplots
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))

    # Plot labeled_zones
    unique_labeled_zones = len(np.unique(labeled_zones)) - 1  # Subtract 1 for background (0)
    cmap_labeled = plt.cm.get_cmap('tab20', unique_labeled_zones)
    im0 = axes[0].imshow(labeled_zones, cmap=cmap_labeled)
    axes[0].set_title(f'Labeled Zones\n({unique_labeled_zones} unique zones)')
    axes[0].set_xticks([])
    axes[0].set_yticks([])
    cbar0 = fig.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.04)
    cbar0.set_label('Zone ID')

    # Plot zone_pattern
    unique_zone_pattern = len(np.unique(zone_pattern)) - 1  # Subtract 1 for background (0)
    cmap_zone = plt.cm.get_cmap('viridis', unique_zone_pattern)
    im1 = axes[1].imshow(zone_pattern, cmap=cmap_zone)
    axes[1].set_title(f'Zone Pattern\n({unique_zone_pattern} unique zones)')
    axes[1].set_xticks([])
    axes[1].set_yticks([])
    cbar1 = fig.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.04)
    cbar1.set_label('Zone ID')

    plt.tight_layout()

    # Save figure if export_path is provided
    if export_path is not None:
        export_path = Path(export_path)
        plot_dir = export_path / 'plots'
        plot_dir.mkdir(parents=True, exist_ok=True)
        fig_path = plot_dir / 'labeled_and_zone_patterns.png'
        fig.savefig(fig_path, dpi=150, bbox_inches='tight')
        print(f"Labeled and zone patterns figure saved to {fig_path}")

    return fig