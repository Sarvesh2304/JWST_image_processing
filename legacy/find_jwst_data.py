#!/usr/bin/env python3
"""
Find Available JWST Data
Searches for available JWST observations and downloads real data
"""

import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from astropy.io import fits
from astropy.visualization import ZScaleInterval
import warnings
warnings.filterwarnings('ignore')

def find_jwst_data():
    """Find available JWST data"""
    
    print("🔍 Searching for Available JWST Data")
    print("=" * 50)
    
    try:
        from astroquery.mast import Observations
        
        # Search for any JWST observations
        print("Searching for JWST observations...")
        
        # Try different search criteria
        search_criteria = [
            {'obs_collection': 'JWST'},
            {'obs_collection': 'JWST', 'instrument_name': 'NIRCam'},
            {'obs_collection': 'JWST', 'instrument_name': 'MIRI'},
            {'obs_collection': 'JWST', 'filters': 'F200W'},
            {'obs_collection': 'JWST', 'filters': 'F444W'},
        ]
        
        for i, criteria in enumerate(search_criteria):
            print(f"\nSearch {i+1}: {criteria}")
            try:
                obs_table = Observations.query_criteria(**criteria)
                print(f"   Found {len(obs_table)} observations")
                
                if len(obs_table) > 0:
                    print(f"   First few targets: {obs_table['target_name'][:5].tolist()}")
                    print(f"   Instruments: {set(obs_table['instrument_name'])}")
                    print(f"   Filters: {set(obs_table['filters'])}")
                    
                    # Try to download the first observation
                    return download_first_observation(obs_table[0])
                    
            except Exception as e:
                print(f"   Error: {e}")
        
        print("\n❌ No JWST observations found with any criteria")
        return []
        
    except ImportError:
        print("❌ astroquery not available")
        return []

def download_first_observation(observation):
    """Download the first available observation"""
    
    print(f"\n📥 Downloading observation: {observation['target_name']}")
    print(f"   Instrument: {observation['instrument_name']}")
    print(f"   Filter: {observation['filters']}")
    
    try:
        from astroquery.mast import Observations
        
        # Get data products for this observation
        data_products = Observations.get_product_list(observation)
        print(f"   Found {len(data_products)} data products")
        
        # Look for different types of data
        data_types = ['RATE', 'CAL', 'UNCAL', 'I2D']
        
        for data_type in data_types:
            products = data_products[data_products['productSubGroupDescription'] == data_type]
            if len(products) > 0:
                print(f"   Found {len(products)} {data_type} files")
                
                # Download first few files
                download_products = products[0:min(3, len(products))]
                
                print(f"   Downloading {len(download_products)} {data_type} files...")
                
                manifest = Observations.download_products(
                    download_products,
                    download_dir="jwst_data/raw"
                )
                
                print(f"   ✅ Downloaded {len(manifest)} files")
                return manifest['Local Path'].tolist()
        
        print("   ❌ No downloadable data products found")
        return []
        
    except Exception as e:
        print(f"   ❌ Error downloading: {e}")
        return []

def process_real_jwst_file(filepath):
    """Process a real JWST FITS file"""
    
    print(f"\n🔧 Processing REAL JWST file: {os.path.basename(filepath)}")
    
    try:
        with fits.open(filepath) as hdul:
            print(f"   FITS file has {len(hdul)} HDUs")
            
            # Try different HDUs to find data
            data = None
            header = None
            hdu_index = 0
            
            for i, hdu in enumerate(hdul):
                if hdu.data is not None:
                    print(f"   HDU {i}: shape {hdu.data.shape}, type {hdu.data.dtype}")
                    if data is None or hdu.data.size > data.size:
                        data = hdu.data
                        header = hdu.header
                        hdu_index = i
            
            if data is None:
                print("   ❌ No data found in any HDU")
                return None
            
            # Get metadata from primary header
            primary_header = hdul[0].header
            filter_name = primary_header.get('FILTER', 'Unknown')
            instrument = primary_header.get('INSTRUME', 'Unknown')
            target = primary_header.get('TARGNAME', 'Unknown')
            obs_id = primary_header.get('OBSERVTN', 'Unknown')
            program = primary_header.get('PROGRAM', 'Unknown')
            
            print(f"   🎯 Target: {target}")
            print(f"   🔬 Instrument: {instrument}")
            print(f"   🌈 Filter: {filter_name}")
            print(f"   📋 Observation ID: {obs_id}")
            print(f"   📊 Program: {program}")
            print(f"   📐 Data shape: {data.shape}")
            print(f"   🔢 Data type: {data.dtype}")
            print(f"   📈 Data range: {np.nanmin(data):.2e} to {np.nanmax(data):.2e}")
            
            # Process the data through our pipeline
            processed_data = process_jwst_pipeline(data, filter_name, target)
            processed_data['header'] = primary_header
            processed_data['instrument'] = instrument
            processed_data['obs_id'] = obs_id
            processed_data['program'] = program
            processed_data['is_real_data'] = True
            processed_data['hdu_index'] = hdu_index
            
            return processed_data
                
    except Exception as e:
        print(f"❌ Error processing {filepath}: {e}")
        return None

def process_jwst_pipeline(data, filter_name, target):
    """Complete JWST processing pipeline for real data"""
    
    print(f"   🔧 Processing REAL {filter_name} data for {target}...")
    
    # Clean data
    data_clean = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    
    # Calibration
    background = np.percentile(data_clean, 5)
    calibrated = data_clean - background
    calibrated = np.maximum(calibrated, 0)
    
    # Denoising
    from scipy import ndimage
    denoised = ndimage.gaussian_filter(calibrated, sigma=1.0)
    
    # Enhancement
    enhanced = np.log1p(denoised * 50)
    
    return {
        'original': data_clean,
        'calibrated': calibrated,
        'denoised': denoised,
        'enhanced': enhanced,
        'filter_name': filter_name,
        'target': target
    }

def create_real_jwst_visualization(processed_data, filename):
    """Create comprehensive visualization for real JWST data"""
    
    print(f"🎨 Creating visualization for REAL JWST data: {filename}")
    
    plt.style.use('dark_background')
    
    # Create a comprehensive visualization
    fig, axes = plt.subplots(2, 3, figsize=(20, 12))
    axes = axes.flatten()
    
    # Processing pipeline
    datasets = [
        (processed_data['original'], "Original REAL JWST Data", "viridis"),
        (processed_data['calibrated'], "Calibrated Data", "viridis"),
        (processed_data['denoised'], "Denoised Data", "viridis"),
        (processed_data['enhanced'], "Enhanced Data", "plasma")
    ]
    
    for i, (data_array, title, cmap) in enumerate(datasets):
        ax = axes[i]
        
        if i == 0:
            norm = LogNorm()
            im = ax.imshow(data_array, cmap=cmap, norm=norm, origin='lower')
        else:
            zscale = ZScaleInterval()
            vmin, vmax = zscale.get_limits(data_array)
            im = ax.imshow(data_array, cmap=cmap, vmin=vmin, vmax=vmax, origin='lower')
        
        ax.set_title(f'{title}\n{processed_data["target"]} - {processed_data["filter_name"]}', fontsize=12)
        ax.set_xlabel('X (pixels)')
        ax.set_ylabel('Y (pixels)')
        ax.grid(True, alpha=0.3)
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    
    # Add some analysis plots
    ax = axes[4]
    # Histogram of pixel values
    ax.hist(processed_data['enhanced'].flatten(), bins=100, alpha=0.7, color='cyan')
    ax.set_title('Pixel Value Distribution', fontsize=12)
    ax.set_xlabel('Pixel Value')
    ax.set_ylabel('Count')
    ax.set_yscale('log')
    ax.grid(True, alpha=0.3)
    
    ax = axes[5]
    # Statistics
    stats_text = f"""
    🎯 Target: {processed_data['target']}
    🌈 Filter: {processed_data['filter_name']}
    🔬 Instrument: {processed_data.get('instrument', 'Unknown')}
    📋 Obs ID: {processed_data.get('obs_id', 'Unknown')}
    📊 Program: {processed_data.get('program', 'Unknown')}
    📁 HDU: {processed_data.get('hdu_index', 'Unknown')}
    
    📐 Data Shape: {processed_data['original'].shape}
    📈 Original Range: {np.nanmin(processed_data['original']):.2e} to {np.nanmax(processed_data['original']):.2e}
    📈 Enhanced Range: {np.nanmin(processed_data['enhanced']):.2e} to {np.nanmax(processed_data['enhanced']):.2e}
    
    ✅ REAL JWST DATA PROCESSED!
    """
    ax.text(0.1, 0.5, stats_text, transform=ax.transAxes, fontsize=10, 
            verticalalignment='center', fontfamily='monospace')
    ax.set_title('Real JWST Data Statistics', fontsize=12)
    ax.axis('off')
    
    plt.suptitle(f'REAL JWST Data Processing - {os.path.splitext(filename)[0]}', fontsize=16)
    plt.tight_layout()
    
    # Save plot
    os.makedirs("jwst_data/visualizations", exist_ok=True)
    save_path = f"jwst_data/visualizations/REAL_jwst_{os.path.splitext(filename)[0]}.png"
    plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
    print(f"✅ Saved REAL JWST visualization: {save_path}")
    
    plt.show()

def main():
    """Main function to find and process real JWST data"""
    
    print("🌌 Finding and Processing REAL JWST Data")
    print("=" * 60)
    print("This script searches for available JWST observations")
    print("and downloads real data from MAST!")
    print()
    
    # Create data directory
    os.makedirs("jwst_data/raw", exist_ok=True)
    os.makedirs("jwst_data/visualizations", exist_ok=True)
    
    # Find and download JWST data
    downloaded_files = find_jwst_data()
    
    if downloaded_files:
        print(f"\n✅ Successfully downloaded {len(downloaded_files)} REAL JWST files!")
        
        # Process each file
        for filepath in downloaded_files:
            processed_data = process_real_jwst_file(filepath)
            if processed_data:
                create_real_jwst_visualization(processed_data, os.path.basename(filepath))
        
        print(f"\n🎉 REAL JWST data processing completed!")
        print(f"📁 Check the 'jwst_data/raw' directory for REAL FITS files")
        print(f"📁 Check the 'jwst_data/visualizations' directory for REAL data plots")
        
    else:
        print("\n❌ No real JWST data could be downloaded.")
        print("This might be due to:")
        print("- Network connectivity issues")
        print("- Data availability")
        print("- API authentication requirements")
        print("\nThe project is ready to process real data when available!")

if __name__ == "__main__":
    main()
