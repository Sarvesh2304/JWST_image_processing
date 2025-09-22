#!/usr/bin/env python3
"""
Create a sample visualization for GitHub
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import os

def create_sample_visualization():
    """Create a sample visualization to show on GitHub"""
    
    print("🎨 Creating sample visualization for GitHub...")
    
    # Create sample data
    size = 512
    x, y = np.meshgrid(np.linspace(-2, 2, size), np.linspace(-2, 2, size))
    
    # Create a spiral galaxy
    r = np.sqrt(x**2 + y**2)
    theta = np.arctan2(y, x)
    
    # Spiral arms
    spiral1 = np.exp(-r/0.8) * np.cos(2 * theta + 3 * r)
    spiral2 = np.exp(-r/1.2) * np.cos(2 * theta + 3 * r + np.pi/3)
    
    # Bulge
    bulge = np.exp(-r**2/0.3)
    
    # Stars
    stars = np.random.poisson(0.1, (size, size))
    
    # Combine
    galaxy = 20 * (spiral1 + spiral2 + 0.4 * bulge + stars)
    galaxy = np.maximum(galaxy, 0)
    
    # Add noise
    noise = np.random.normal(0, 0.5, (size, size))
    galaxy += noise
    galaxy = np.maximum(galaxy, 0)
    
    # Create visualization
    plt.style.use('dark_background')
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    
    # Original
    im1 = axes[0,0].imshow(galaxy, cmap='viridis', norm=LogNorm(), origin='lower')
    axes[0,0].set_title('Original JWST-like Data', fontsize=14)
    axes[0,0].set_xlabel('X (pixels)')
    axes[0,0].set_ylabel('Y (pixels)')
    plt.colorbar(im1, ax=axes[0,0], fraction=0.046, pad=0.04)
    
    # Enhanced
    enhanced = np.log1p(galaxy * 10)
    im2 = axes[0,1].imshow(enhanced, cmap='plasma', origin='lower')
    axes[0,1].set_title('Enhanced Data', fontsize=14)
    axes[0,1].set_xlabel('X (pixels)')
    axes[0,1].set_ylabel('Y (pixels)')
    plt.colorbar(im2, ax=axes[0,1], fraction=0.046, pad=0.04)
    
    # RGB composite
    r_data = enhanced
    g_data = np.roll(enhanced, 10, axis=0)
    b_data = np.roll(enhanced, 20, axis=0)
    
    rgb_data = np.stack([r_data, g_data, b_data], axis=2)
    rgb_data = (rgb_data - np.percentile(rgb_data, 1)) / (np.percentile(rgb_data, 99) - np.percentile(rgb_data, 1))
    rgb_data = np.clip(rgb_data, 0, 1)
    
    axes[1,0].imshow(rgb_data, origin='lower')
    axes[1,0].set_title('RGB Composite', fontsize=14)
    axes[1,0].set_xlabel('X (pixels)')
    axes[1,0].set_ylabel('Y (pixels)')
    
    # Statistics
    axes[1,1].hist(enhanced.flatten(), bins=50, alpha=0.7, color='cyan')
    axes[1,1].set_title('Pixel Value Distribution', fontsize=14)
    axes[1,1].set_xlabel('Pixel Value')
    axes[1,1].set_ylabel('Count')
    axes[1,1].set_yscale('log')
    axes[1,1].grid(True, alpha=0.3)
    
    plt.suptitle('JWST Image Processing Pipeline - Sample Output', fontsize=16)
    plt.tight_layout()
    
    # Save
    os.makedirs("jwst_data/visualizations", exist_ok=True)
    save_path = "jwst_data/visualizations/sample_jwst_processing.png"
    plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='black')
    print(f"✅ Created sample visualization: {save_path}")
    
    plt.show()

if __name__ == "__main__":
    create_sample_visualization()
