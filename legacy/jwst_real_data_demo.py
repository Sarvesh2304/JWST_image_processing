"""
JWST Real Data Demo
Downloads and processes real JWST data using alternative methods
"""

import os
import requests
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from astropy.io import fits
from astropy.visualization import ZScaleInterval
import warnings
warnings.filterwarnings('ignore')

def download_jwst_sample_data():
    """Download some sample JWST data from public sources"""
    
    print("🌌 Downloading real JWST sample data...")
    
    # Create data directory
    os.makedirs("jwst_data/raw", exist_ok=True)
    os.makedirs("jwst_data/visualizations", exist_ok=True)
    
    # Sample JWST data URLs (these are publicly available).
    # Files keep their archive names. These are Stage-1 rate files (DN/s, no WCS) from
    # program 2756 (DDT imaging of Abell 2744), taken on NRCA1, a short-wavelength detector.
    # They are NOT NGC 3132 and NOT F444W/F277W: earlier versions of this script saved them
    # under those fabricated names. See docs/lab-roadmap/01-repository-audit.md (S18).
    sample_urls = [
        {
            "name": "jw02756001001_02101_00001_nrca1_rate.fits",
            "url": "https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/jw02756001001_02101_00001_nrca1_rate.fits",
            "description": "JWST program 2756, NIRCam NRCA1 rate file, exposure 00001"
        },
        {
            "name": "jw02756001001_02101_00002_nrca1_rate.fits",
            "url": "https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/jw02756001001_02101_00002_nrca1_rate.fits",
            "description": "JWST program 2756, NIRCam NRCA1 rate file, exposure 00002"
        }
    ]
    
    downloaded_files = []
    
    for sample in sample_urls:
        try:
            print(f"Downloading {sample['description']}...")
            response = requests.get(sample['url'], timeout=30)
            
            if response.status_code == 200:
                filepath = os.path.join("jwst_data/raw", sample['name'])
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                downloaded_files.append(filepath)
                print(f"✅ Downloaded: {sample['name']}")
            else:
                print(f"❌ Failed to download {sample['name']}: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error downloading {sample['name']}: {e}")
    
    return downloaded_files

def create_synthetic_jwst_like_data():
    """Create realistic JWST-like data when real data isn't available"""
    
    print("🎨 Creating realistic JWST-like data...")
    
    # Create a more realistic galaxy simulation
    size = 512
    x = np.linspace(-8, 8, size)
    y = np.linspace(-8, 8, size)
    X, Y = np.meshgrid(x, y)
    
    # Create a more complex galaxy structure
    r = np.sqrt(X**2 + Y**2)
    theta = np.arctan2(Y, X)
    
    # Multiple spiral arms
    spiral1 = np.exp(-r/4) * np.cos(3 * theta + 4 * r)
    spiral2 = np.exp(-r/4) * np.cos(3 * theta + 4 * r + 2*np.pi/3)
    spiral3 = np.exp(-r/4) * np.cos(3 * theta + 4 * r + 4*np.pi/3)
    
    # Central bulge
    bulge = 2 * np.exp(-r**2/3)
    
    # Add some star-forming regions
    star_regions = 0.5 * np.exp(-((X-2)**2 + (Y-1)**2)/2) + \
                   0.3 * np.exp(-((X+1)**2 + (Y+2)**2)/1.5)
    
    # Add realistic noise
    noise = np.random.normal(0, 0.2, (size, size))
    
    # Combine components
    galaxy = 15 * (spiral1 + spiral2 + spiral3 + 0.3 * bulge + star_regions) + noise
    
    # Ensure positive values
    galaxy = np.maximum(galaxy, 0)
    
    return galaxy

def process_jwst_data(data, filter_name="Unknown"):
    """Process JWST data through the pipeline"""
    
    print(f"🔧 Processing {filter_name} data...")
    
    # Basic calibration
    background = np.percentile(data, 5)
    calibrated = data - background
    calibrated = np.maximum(calibrated, 0)
    
    # Denoise
    from scipy import ndimage
    denoised = ndimage.gaussian_filter(calibrated, sigma=1.2)
    
    # Enhance contrast
    enhanced = np.log1p(denoised * 50)
    
    return calibrated, denoised, enhanced

def create_real_data_visualizations():
    """Create visualizations with real or realistic JWST data"""
    
    print("🌌 JWST Real Data Processing Demo")
    print("=" * 50)
    
    # Try to download real data first
    real_files = download_jwst_sample_data()
    
    if real_files:
        print(f"\n✅ Successfully downloaded {len(real_files)} real JWST files!")
        process_real_files(real_files)
    else:
        print("\n📡 Real data download failed, creating realistic JWST-like data...")
        process_synthetic_realistic_data()

def process_real_files(files):
    """Process real JWST FITS files"""
    
    processed_data = {}
    
    for filepath in files:
        try:
            print(f"\n📁 Processing {os.path.basename(filepath)}...")
            
            # Load FITS file
            with fits.open(filepath) as hdul:
                data = hdul[0].data
                header = hdul[0].header
                
                # Get filter information
                filter_name = header.get('FILTER', 'Unknown')
                instrument = header.get('INSTRUME', 'Unknown')
                
                print(f"   Instrument: {instrument}")
                print(f"   Filter: {filter_name}")
                print(f"   Data shape: {data.shape}")
                print(f"   Data range: {np.nanmin(data):.2e} to {np.nanmax(data):.2e}")
                
                # Process the data
                calibrated, denoised, enhanced = process_jwst_data(data, filter_name)
                
                processed_data[filter_name] = {
                    'original': data,
                    'calibrated': calibrated,
                    'denoised': denoised,
                    'enhanced': enhanced,
                    'header': header
                }
                
        except Exception as e:
            print(f"❌ Error processing {filepath}: {e}")
    
    # Create visualizations
    create_visualizations(processed_data, "Real JWST Data")

def process_synthetic_realistic_data():
    """Process realistic synthetic data that mimics JWST observations"""
    
    print("\n🎨 Creating realistic JWST-like observations...")
    
    # Create data for different filters
    filters = {
        'F090W': create_synthetic_jwst_like_data(),
        'F277W': create_synthetic_jwst_like_data() * 0.8,  # Different sensitivity
        'F444W': create_synthetic_jwst_like_data() * 1.2   # Different wavelength
    }
    
    processed_data = {}
    
    for filter_name, data in filters.items():
        print(f"Processing {filter_name}...")
        calibrated, denoised, enhanced = process_jwst_data(data, filter_name)
        
        processed_data[filter_name] = {
            'original': data,
            'calibrated': calibrated,
            'denoised': denoised,
            'enhanced': enhanced
        }
    
    # Create visualizations
    create_visualizations(processed_data, "Realistic JWST-like Data")

def create_visualizations(processed_data, data_type):
    """Create beautiful visualizations"""
    
    print(f"\n🎨 Creating visualizations for {data_type}...")
    
    # Set up plotting style
    plt.style.use('dark_background')
    
    # Create processing pipeline plot
    create_pipeline_plot(processed_data, data_type)
    
    # Create multi-filter plot
    create_multi_filter_plot(processed_data, data_type)
    
    # Create RGB composite if we have multiple filters
    if len(processed_data) >= 3:
        create_rgb_composite(processed_data, data_type)

def create_pipeline_plot(processed_data, data_type):
    """Create processing pipeline visualization"""
    
    # Use the first filter for pipeline demonstration
    filter_name = list(processed_data.keys())[0]
    data = processed_data[filter_name]
    
    fig, axes = plt.subplots(2, 2, figsize=(15, 12))
    axes = axes.flatten()
    
    datasets = [
        (data['original'], "Original JWST Data", "viridis"),
        (data['calibrated'], "Calibrated (Background Removed)", "viridis"),
        (data['denoised'], "Denoised (Noise Reduction)", "viridis"),
        (data['enhanced'], "Enhanced (Contrast Stretched)", "plasma")
    ]
    
    for i, (data_array, title, cmap) in enumerate(datasets):
        ax = axes[i]
        
        # Use appropriate normalization
        if i == 0:  # Original data
            norm = LogNorm()
        else:
            # Use ZScale interval for normalization
            zscale = ZScaleInterval()
            vmin, vmax = zscale.get_limits(data_array)
            norm = None  # Will use vmin, vmax directly
        
        if norm is None:
            im = ax.imshow(data_array, cmap=cmap, vmin=vmin, vmax=vmax, origin='lower')
        else:
            im = ax.imshow(data_array, cmap=cmap, norm=norm, origin='lower')
        ax.set_title(f'{title}\n{filter_name}', fontsize=12, pad=15)
        ax.set_xlabel('X (pixels)')
        ax.set_ylabel('Y (pixels)')
        ax.grid(True, alpha=0.3)
        
        # Add colorbar
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    
    plt.suptitle(f'JWST Image Processing Pipeline - {data_type}', fontsize=16, y=0.95)
    plt.tight_layout()
    
    # Save the plot
    save_path = f"jwst_data/visualizations/{data_type.lower().replace(' ', '_')}_pipeline.png"
    plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
    print(f"✅ Saved pipeline plot: {save_path}")

def create_multi_filter_plot(processed_data, data_type):
    """Create multi-filter visualization"""
    
    n_filters = len(processed_data)
    n_cols = min(3, n_filters)
    n_rows = (n_filters + n_cols - 1) // n_cols
    
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5*n_cols, 5*n_rows))
    
    if n_filters == 1:
        axes = [axes]
    elif n_rows == 1:
        axes = axes.reshape(1, -1)
    
    axes = axes.flatten()
    
    for i, (filter_name, data) in enumerate(processed_data.items()):
        ax = axes[i]
        
        # Plot enhanced data
        zscale = ZScaleInterval()
        vmin, vmax = zscale.get_limits(data['enhanced'])
        im = ax.imshow(data['enhanced'], cmap='plasma', vmin=vmin, vmax=vmax, origin='lower')
        ax.set_title(f'{filter_name} Filter', fontsize=14)
        ax.set_xlabel('X (pixels)')
        ax.set_ylabel('Y (pixels)')
        ax.grid(True, alpha=0.3)
        
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    
    # Hide unused subplots
    for i in range(n_filters, len(axes)):
        axes[i].set_visible(False)
    
    plt.suptitle(f'JWST Multi-Filter View - {data_type}', fontsize=16, y=0.95)
    plt.tight_layout()
    
    # Save the plot
    save_path = f"jwst_data/visualizations/{data_type.lower().replace(' ', '_')}_multi_filter.png"
    plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
    print(f"✅ Saved multi-filter plot: {save_path}")

def create_rgb_composite(processed_data, data_type):
    """Create RGB composite from multiple filters"""
    
    filter_names = list(processed_data.keys())
    
    if len(filter_names) >= 3:
        # Use first three filters for RGB
        red_data = processed_data[filter_names[0]]['enhanced']
        green_data = processed_data[filter_names[1]]['enhanced']
        blue_data = processed_data[filter_names[2]]['enhanced']
        
        # Normalize each channel
        def normalize_channel(data):
            data_norm = (data - np.percentile(data, 1)) / (np.percentile(data, 99) - np.percentile(data, 1))
            return np.clip(data_norm, 0, 1)
        
        red_norm = normalize_channel(red_data)
        green_norm = normalize_channel(green_data)
        blue_norm = normalize_channel(blue_data)
        
        # Create RGB array
        rgb_data = np.stack([red_norm, green_norm, blue_norm], axis=2)
        
        # Plot RGB composite
        plt.figure(figsize=(12, 10))
        plt.imshow(rgb_data, origin='lower')
        plt.title(f'JWST RGB Composite - {data_type}\nR: {filter_names[0]}, G: {filter_names[1]}, B: {filter_names[2]}', 
                 fontsize=16, pad=20)
        plt.xlabel('X (pixels)', fontsize=12)
        plt.ylabel('Y (pixels)', fontsize=12)
        plt.grid(True, alpha=0.3)
        
        # Save the plot
        save_path = f"jwst_data/visualizations/{data_type.lower().replace(' ', '_')}_rgb_composite.png"
        plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
        print(f"✅ Saved RGB composite: {save_path}")

def main():
    """Main function"""
    create_real_data_visualizations()
    print("\n🎉 Real data processing completed!")
    print("📁 Check the 'jwst_data/visualizations' directory for results")

if __name__ == "__main__":
    main()
