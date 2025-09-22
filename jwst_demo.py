"""
JWST Image Processing Demo
A simplified demo that creates synthetic JWST-like data for demonstration
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import os

def create_synthetic_jwst_data():
    """Create synthetic JWST-like data for demonstration"""
    
    # Create a synthetic galaxy image
    size = 512
    x = np.linspace(-5, 5, size)
    y = np.linspace(-5, 5, size)
    X, Y = np.meshgrid(x, y)
    
    # Create a spiral galaxy
    r = np.sqrt(X**2 + Y**2)
    theta = np.arctan2(Y, X)
    
    # Spiral arms
    spiral1 = np.exp(-r/3) * np.cos(2 * theta + 3 * r)
    spiral2 = np.exp(-r/3) * np.cos(2 * theta + 3 * r + np.pi)
    
    # Central bulge
    bulge = np.exp(-r**2/2)
    
    # Add some noise
    noise = np.random.normal(0, 0.1, (size, size))
    
    # Combine components
    galaxy = 10 * (spiral1 + spiral2 + 0.5 * bulge) + noise
    
    # Ensure positive values
    galaxy = np.maximum(galaxy, 0)
    
    return galaxy

def process_image(data):
    """Simple image processing pipeline"""
    
    # Basic calibration (remove background)
    background = np.percentile(data, 10)
    calibrated = data - background
    calibrated = np.maximum(calibrated, 0)
    
    # Denoise (simple Gaussian filter)
    from scipy import ndimage
    denoised = ndimage.gaussian_filter(calibrated, sigma=1.0)
    
    # Enhance contrast (log scaling)
    enhanced = np.log1p(denoised * 100)
    
    return calibrated, denoised, enhanced

def create_visualizations():
    """Create beautiful visualizations of the synthetic data"""
    
    print("🌌 Creating synthetic JWST data...")
    
    # Create synthetic data
    galaxy_data = create_synthetic_jwst_data()
    
    # Process the data
    calibrated, denoised, enhanced = process_image(galaxy_data)
    
    # Create output directory
    os.makedirs("jwst_data/visualizations", exist_ok=True)
    
    # Set up the plot style
    plt.style.use('dark_background')
    
    # Create a 2x2 subplot
    fig, axes = plt.subplots(2, 2, figsize=(15, 12))
    axes = axes.flatten()
    
    # Plot original data
    im1 = axes[0].imshow(galaxy_data, cmap='viridis', origin='lower')
    axes[0].set_title('Original Synthetic Galaxy', fontsize=14, pad=20)
    axes[0].set_xlabel('X (pixels)')
    axes[0].set_ylabel('Y (pixels)')
    axes[0].grid(True, alpha=0.3)
    plt.colorbar(im1, ax=axes[0], fraction=0.046, pad=0.04)
    
    # Plot calibrated data
    im2 = axes[1].imshow(calibrated, cmap='viridis', origin='lower')
    axes[1].set_title('Calibrated (Background Removed)', fontsize=14, pad=20)
    axes[1].set_xlabel('X (pixels)')
    axes[1].set_ylabel('Y (pixels)')
    axes[1].grid(True, alpha=0.3)
    plt.colorbar(im2, ax=axes[1], fraction=0.046, pad=0.04)
    
    # Plot denoised data
    im3 = axes[2].imshow(denoised, cmap='viridis', origin='lower')
    axes[2].set_title('Denoised (Gaussian Filter)', fontsize=14, pad=20)
    axes[2].set_xlabel('X (pixels)')
    axes[2].set_ylabel('Y (pixels)')
    axes[2].grid(True, alpha=0.3)
    plt.colorbar(im3, ax=axes[2], fraction=0.046, pad=0.04)
    
    # Plot enhanced data
    im4 = axes[3].imshow(enhanced, cmap='plasma', origin='lower')
    axes[3].set_title('Enhanced (Log Scaling)', fontsize=14, pad=20)
    axes[3].set_xlabel('X (pixels)')
    axes[3].set_ylabel('Y (pixels)')
    axes[3].grid(True, alpha=0.3)
    plt.colorbar(im4, ax=axes[3], fraction=0.046, pad=0.04)
    
    plt.suptitle('JWST Image Processing Pipeline - Synthetic Galaxy', fontsize=18, y=0.95)
    plt.tight_layout()
    
    # Save the plot
    save_path = "jwst_data/visualizations/synthetic_galaxy_pipeline.png"
    plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
    print(f"✅ Saved visualization: {save_path}")
    
    # Create a beautiful single image
    plt.figure(figsize=(12, 10))
    plt.imshow(enhanced, cmap='plasma', origin='lower')
    plt.title('Synthetic Spiral Galaxy - JWST Style', fontsize=16, pad=20)
    plt.xlabel('X (pixels)', fontsize=12)
    plt.ylabel('Y (pixels)', fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.colorbar(label='Enhanced Flux', fraction=0.046, pad=0.04)
    
    save_path2 = "jwst_data/visualizations/synthetic_galaxy_final.png"
    plt.savefig(save_path2, dpi=300, bbox_inches='tight', facecolor='black')
    print(f"✅ Saved final image: {save_path2}")
    
    # Create a multi-filter simulation
    create_multi_filter_demo()
    
    plt.show()

def create_multi_filter_demo():
    """Create a multi-filter demonstration"""
    
    print("🎨 Creating multi-filter demonstration...")
    
    # Create synthetic data for different "filters"
    size = 256
    x = np.linspace(-3, 3, size)
    y = np.linspace(-3, 3, size)
    X, Y = np.meshgrid(x, y)
    r = np.sqrt(X**2 + Y**2)
    
    # Simulate different filters with different characteristics
    filters = {
        'F090W': np.exp(-r**2/4) + 0.3 * np.random.normal(0, 1, (size, size)),
        'F277W': np.exp(-r**2/3) + 0.2 * np.random.normal(0, 1, (size, size)),
        'F444W': np.exp(-r**2/2) + 0.1 * np.random.normal(0, 1, (size, size))
    }
    
    # Process each filter
    processed_filters = {}
    for filter_name, data in filters.items():
        calibrated, denoised, enhanced = process_image(data)
        processed_filters[filter_name] = enhanced
    
    # Create RGB composite
    rgb_data = np.stack([
        processed_filters['F444W'],  # Red
        processed_filters['F277W'],  # Green
        processed_filters['F090W']   # Blue
    ], axis=2)
    
    # Normalize each channel
    for i in range(3):
        rgb_data[:, :, i] = (rgb_data[:, :, i] - np.percentile(rgb_data[:, :, i], 1)) / \
                           (np.percentile(rgb_data[:, :, i], 99) - np.percentile(rgb_data[:, :, i], 1))
        rgb_data[:, :, i] = np.clip(rgb_data[:, :, i], 0, 1)
    
    # Create multi-filter plot
    fig, axes = plt.subplots(2, 2, figsize=(15, 12))
    
    # Individual filters
    filter_names = list(filters.keys())
    for i, (filter_name, data) in enumerate(processed_filters.items()):
        ax = axes[i//2, i%2]
        im = ax.imshow(data, cmap='viridis', origin='lower')
        ax.set_title(f'{filter_name} Filter', fontsize=14)
        ax.set_xlabel('X (pixels)')
        ax.set_ylabel('Y (pixels)')
        ax.grid(True, alpha=0.3)
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    
    # RGB composite
    ax = axes[1, 1]
    ax.imshow(rgb_data, origin='lower')
    ax.set_title('RGB Composite\nR:F444W, G:F277W, B:F090W', fontsize=14)
    ax.set_xlabel('X (pixels)')
    ax.set_ylabel('Y (pixels)')
    ax.grid(True, alpha=0.3)
    
    plt.suptitle('JWST Multi-Filter Simulation', fontsize=18, y=0.95)
    plt.tight_layout()
    
    # Save the plot
    save_path = "jwst_data/visualizations/multi_filter_demo.png"
    plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
    print(f"✅ Saved multi-filter demo: {save_path}")
    
    plt.show()

def main():
    """Main demo function"""
    
    print("🌌 JWST Image Processing Demo")
    print("=" * 50)
    print("This demo creates synthetic JWST-like data to demonstrate")
    print("the image processing pipeline without requiring real data.")
    print()
    
    try:
        create_visualizations()
        print("\n🎉 Demo completed successfully!")
        print("📁 Check the 'jwst_data/visualizations' directory for results")
        
    except Exception as e:
        print(f"❌ Error running demo: {e}")
        print("This might be due to missing dependencies.")
        print("Try installing: pip install matplotlib scipy")

if __name__ == "__main__":
    main()

