"""
JWST Visualizer
Creates beautiful visualizations of James Webb Space Telescope data
"""

import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
from matplotlib.colors import LogNorm, PowerNorm, LinearSegmentedColormap
import matplotlib.patches as mpatches
from astropy.visualization import ZScaleInterval, ImageNormalize
from astropy.visualization import AsinhStretch, SqrtStretch, LogStretch
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import warnings
warnings.filterwarnings('ignore')

class JWSTVisualizer:
    """Create beautiful visualizations of JWST data"""
    
    def __init__(self, data_dir: str = "jwst_data"):
        self.data_dir = data_dir
        self.output_dir = os.path.join(data_dir, "visualizations")
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Set up matplotlib style
        plt.style.use('dark_background')
        self.setup_custom_colormaps()
    
    def setup_custom_colormaps(self):
        """Create custom colormaps for astronomical data"""
        
        # Hubble-like colormap
        colors_hubble = ['#000000', '#000080', '#0000FF', '#00FFFF', '#FFFF00', '#FFFFFF']
        n_bins = 256
        self.cmap_hubble = LinearSegmentedColormap.from_list('hubble', colors_hubble, N=n_bins)
        
        # Infrared colormap
        colors_ir = ['#000000', '#8B0000', '#FF4500', '#FFD700', '#FFFFFF']
        self.cmap_infrared = LinearSegmentedColormap.from_list('infrared', colors_ir, N=n_bins)
        
        # Cosmic colormap
        colors_cosmic = ['#000000', '#4B0082', '#0000FF', '#00FFFF', '#FFFF00', '#FF69B4', '#FFFFFF']
        self.cmap_cosmic = LinearSegmentedColormap.from_list('cosmic', colors_cosmic, N=n_bins)
    
    def plot_single_image(self, 
                         data: np.ndarray, 
                         title: str = "JWST Image",
                         filter_name: str = "",
                         stretch: str = 'asinh',
                         colormap: str = 'hubble',
                         save_path: str = None) -> plt.Figure:
        """
        Plot a single JWST image
        
        Parameters:
        -----------
        data : numpy.ndarray
            Image data
        title : str
            Plot title
        filter_name : str
            Filter name for labeling
        stretch : str
            Stretch function ('linear', 'log', 'sqrt', 'asinh')
        colormap : str
            Colormap name
        save_path : str
            Path to save the plot
        """
        
        # Choose colormap
        cmap_dict = {
            'hubble': self.cmap_hubble,
            'infrared': self.cmap_infrared,
            'cosmic': self.cmap_cosmic,
            'viridis': 'viridis',
            'plasma': 'plasma',
            'inferno': 'inferno',
            'magma': 'magma'
        }
        cmap = cmap_dict.get(colormap, 'viridis')
        
        # Choose stretch function
        if stretch == 'asinh':
            stretch_func = AsinhStretch()
        elif stretch == 'log':
            stretch_func = LogStretch()
        elif stretch == 'sqrt':
            stretch_func = SqrtStretch()
        else:
            stretch_func = None
        
        # Create normalization
        if stretch_func:
            norm = ImageNormalize(data, interval=ZScaleInterval(), stretch=stretch_func)
        else:
            norm = ZScaleInterval()
        
        # Create figure
        fig, ax = plt.subplots(figsize=(12, 10))
        
        # Plot image
        im = ax.imshow(data, cmap=cmap, norm=norm, origin='lower')
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label(f'Flux ({filter_name})', rotation=270, labelpad=20)
        
        # Formatting
        ax.set_title(f'{title}\nFilter: {filter_name}', fontsize=16, pad=20)
        ax.set_xlabel('X (pixels)', fontsize=12)
        ax.set_ylabel('Y (pixels)', fontsize=12)
        
        # Add grid
        ax.grid(True, alpha=0.3)
        
        # Save if requested
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
            print(f"Saved plot: {save_path}")
        
        return fig
    
    def plot_rgb_composite(self, 
                          rgb_data: np.ndarray,
                          title: str = "JWST RGB Composite",
                          filters_used: list = None,
                          save_path: str = None) -> plt.Figure:
        """
        Plot RGB composite image
        
        Parameters:
        -----------
        rgb_data : numpy.ndarray
            RGB image data (H, W, 3)
        title : str
            Plot title
        filters_used : list
            List of filters used for R, G, B
        save_path : str
            Path to save the plot
        """
        
        fig, ax = plt.subplots(figsize=(14, 12))
        
        # Plot RGB image
        ax.imshow(rgb_data, origin='lower')
        
        # Formatting
        filter_text = f"R: {filters_used[0]}, G: {filters_used[1]}, B: {filters_used[2]}" if filters_used else ""
        ax.set_title(f'{title}\n{filter_text}', fontsize=16, pad=20)
        ax.set_xlabel('X (pixels)', fontsize=12)
        ax.set_ylabel('Y (pixels)', fontsize=12)
        
        # Add grid
        ax.grid(True, alpha=0.3)
        
        # Save if requested
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
            print(f"Saved RGB composite: {save_path}")
        
        return fig
    
    def plot_processing_pipeline(self, 
                               original_data: np.ndarray,
                               calibrated_data: np.ndarray,
                               denoised_data: np.ndarray,
                               enhanced_data: np.ndarray,
                               filter_name: str = "",
                               save_path: str = None) -> plt.Figure:
        """
        Plot the image processing pipeline
        
        Parameters:
        -----------
        original_data, calibrated_data, denoised_data, enhanced_data : numpy.ndarray
            Data at each processing step
        filter_name : str
            Filter name
        save_path : str
            Path to save the plot
        """
        
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        axes = axes.flatten()
        
        datasets = [
            (original_data, "Original", "viridis"),
            (calibrated_data, "Calibrated", "viridis"),
            (denoised_data, "Denoised", "viridis"),
            (enhanced_data, "Enhanced", "hubble")
        ]
        
        for i, (data, title, cmap) in enumerate(datasets):
            ax = axes[i]
            
            # Use appropriate normalization
            if i == 0:  # Original data
                norm = LogNorm()
            else:
                norm = ZScaleInterval()
            
            im = ax.imshow(data, cmap=cmap, norm=norm, origin='lower')
            ax.set_title(f'{title}\n{filter_name}', fontsize=12)
            ax.set_xlabel('X (pixels)')
            ax.set_ylabel('Y (pixels)')
            ax.grid(True, alpha=0.3)
            
            # Add colorbar
            plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        
        plt.suptitle(f'JWST Image Processing Pipeline - {filter_name}', fontsize=16)
        plt.tight_layout()
        
        # Save if requested
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
            print(f"Saved processing pipeline: {save_path}")
        
        return fig
    
    def plot_source_catalog(self, 
                           data: np.ndarray,
                           catalog,
                           title: str = "Source Detection",
                           filter_name: str = "",
                           save_path: str = None) -> plt.Figure:
        """
        Plot image with detected sources overlaid
        
        Parameters:
        -----------
        data : numpy.ndarray
            Image data
        catalog : photutils.segmentation.SourceCatalog
            Source catalog
        title : str
            Plot title
        filter_name : str
            Filter name
        save_path : str
            Path to save the plot
        """
        
        fig, ax = plt.subplots(figsize=(12, 10))
        
        # Plot image
        norm = ZScaleInterval()
        im = ax.imshow(data, cmap='viridis', norm=norm, origin='lower')
        
        # Overlay sources
        if catalog is not None and len(catalog) > 0:
            # Plot source positions
            ax.scatter(catalog.xcentroid, catalog.ycentroid, 
                      c='red', s=50, marker='x', linewidths=2, label=f'{len(catalog)} sources')
            
            # Plot source ellipses
            for source in catalog:
                # Get source properties
                x, y = source.xcentroid, source.ycentroid
                a, b = source.semimajor_axis_sigma, source.semiminor_axis_sigma
                theta = source.orientation.to(u.rad).value
                
                # Create ellipse
                ellipse = mpatches.Ellipse((x, y), 2*a, 2*b, angle=np.degrees(theta),
                                         fill=False, edgecolor='yellow', linewidth=1, alpha=0.7)
                ax.add_patch(ellipse)
        
        # Formatting
        ax.set_title(f'{title}\nFilter: {filter_name}', fontsize=16, pad=20)
        ax.set_xlabel('X (pixels)', fontsize=12)
        ax.set_ylabel('Y (pixels)', fontsize=12)
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label(f'Flux ({filter_name})', rotation=270, labelpad=20)
        
        # Save if requested
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
            print(f"Saved source catalog plot: {save_path}")
        
        return fig
    
    def plot_multiple_filters(self, 
                            processed_filters: dict,
                            title: str = "JWST Multi-Filter View",
                            save_path: str = None) -> plt.Figure:
        """
        Plot multiple filter images in a grid
        
        Parameters:
        -----------
        processed_filters : dict
            Dictionary of processed filter data
        title : str
            Plot title
        save_path : str
            Path to save the plot
        """
        
        n_filters = len([k for k in processed_filters.keys() if k != 'composite'])
        n_cols = min(3, n_filters)
        n_rows = (n_filters + n_cols - 1) // n_cols
        
        fig, axes = plt.subplots(n_rows, n_cols, figsize=(5*n_cols, 5*n_rows))
        if n_filters == 1:
            axes = [axes]
        elif n_rows == 1:
            axes = axes.reshape(1, -1)
        
        axes = axes.flatten()
        
        # Plot each filter
        for i, (filter_name, result) in enumerate(processed_filters.items()):
            if filter_name == 'composite':
                continue
                
            ax = axes[i]
            data = result['enhanced_data']
            
            # Plot image
            norm = ZScaleInterval()
            im = ax.imshow(data, cmap='viridis', norm=norm, origin='lower')
            
            # Formatting
            ax.set_title(f'{filter_name}', fontsize=12)
            ax.set_xlabel('X (pixels)')
            ax.set_ylabel('Y (pixels)')
            ax.grid(True, alpha=0.3)
            
            # Add colorbar
            plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        
        # Hide unused subplots
        for i in range(n_filters, len(axes)):
            axes[i].set_visible(False)
        
        plt.suptitle(title, fontsize=16)
        plt.tight_layout()
        
        # Save if requested
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
            print(f"Saved multi-filter plot: {save_path}")
        
        return fig
    
    def create_publication_plot(self, 
                              processed_filters: dict,
                              target_name: str = "JWST Target",
                              save_path: str = None) -> plt.Figure:
        """
        Create a publication-quality plot
        
        Parameters:
        -----------
        processed_filters : dict
            Dictionary of processed filter data
        target_name : str
            Target name
        save_path : str
            Path to save the plot
        """
        
        # Determine layout
        n_filters = len([k for k in processed_filters.keys() if k != 'composite'])
        has_composite = 'composite' in processed_filters
        
        if has_composite and n_filters > 0:
            # Layout with composite and individual filters
            fig = plt.figure(figsize=(20, 12))
            
            # Main composite plot (left side)
            ax_main = plt.subplot2grid((2, 3), (0, 0), rowspan=2, colspan=2)
            
            # Individual filter plots (right side)
            ax1 = plt.subplot2grid((2, 3), (0, 2))
            ax2 = plt.subplot2grid((2, 3), (1, 2))
            
            # Plot composite
            composite = processed_filters['composite']
            ax_main.imshow(composite['rgb_data'], origin='lower')
            ax_main.set_title(f'{target_name} - RGB Composite', fontsize=16, pad=20)
            ax_main.set_xlabel('X (pixels)', fontsize=12)
            ax_main.set_ylabel('Y (pixels)', fontsize=12)
            ax_main.grid(True, alpha=0.3)
            
            # Plot individual filters
            filter_items = [(k, v) for k, v in processed_filters.items() if k != 'composite']
            for i, (filter_name, result) in enumerate(filter_items[:2]):
                ax = [ax1, ax2][i]
                data = result['enhanced_data']
                
                norm = ZScaleInterval()
                im = ax.imshow(data, cmap='viridis', norm=norm, origin='lower')
                ax.set_title(f'{filter_name}', fontsize=12)
                ax.set_xlabel('X (pixels)')
                ax.set_ylabel('Y (pixels)')
                ax.grid(True, alpha=0.3)
                
                plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        
        else:
            # Simple grid layout
            n_cols = min(3, n_filters)
            n_rows = (n_filters + n_cols - 1) // n_cols
            fig, axes = plt.subplots(n_rows, n_cols, figsize=(6*n_cols, 6*n_rows))
            
            if n_filters == 1:
                axes = [axes]
            elif n_rows == 1:
                axes = axes.reshape(1, -1)
            
            axes = axes.flatten()
            
            for i, (filter_name, result) in enumerate(processed_filters.items()):
                if filter_name == 'composite':
                    continue
                    
                ax = axes[i]
                data = result['enhanced_data']
                
                norm = ZScaleInterval()
                im = ax.imshow(data, cmap='viridis', norm=norm, origin='lower')
                ax.set_title(f'{filter_name}', fontsize=14)
                ax.set_xlabel('X (pixels)')
                ax.set_ylabel('Y (pixels)')
                ax.grid(True, alpha=0.3)
                
                plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            
            # Hide unused subplots
            for i in range(n_filters, len(axes)):
                axes[i].set_visible(False)
        
        plt.suptitle(f'James Webb Space Telescope - {target_name}', fontsize=20, y=0.95)
        plt.tight_layout()
        
        # Save if requested
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
            print(f"Saved publication plot: {save_path}")
        
        return fig

# Example usage
if __name__ == "__main__":
    visualizer = JWSTVisualizer()
    print("JWST Visualizer initialized. Ready to create beautiful plots!")
