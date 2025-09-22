"""
JWST Image Processing Pipeline - Main Script
Complete pipeline for downloading, processing, and visualizing James Webb Space Telescope data
"""

import os
import sys
import argparse
from pathlib import Path

# Import our custom modules
from jwst_data_downloader import JWSTDataDownloader
from jwst_image_processor import JWSTImageProcessor
from jwst_visualizer import JWSTVisualizer

def main():
    """Main function to run the JWST processing pipeline"""
    
    parser = argparse.ArgumentParser(description='JWST Image Processing Pipeline')
    parser.add_argument('--target', type=str, default='NGC 3132', 
                       help='Target name (e.g., "NGC 3132", "M51", "Stephan\'s Quintet")')
    parser.add_argument('--instrument', type=str, default='NIRCam',
                       choices=['NIRCam', 'NIRSpec', 'MIRI', 'NIRISS'],
                       help='JWST instrument')
    parser.add_argument('--max-files', type=int, default=5,
                       help='Maximum number of files to download')
    parser.add_argument('--download-only', action='store_true',
                       help='Only download data, do not process')
    parser.add_argument('--process-only', action='store_true',
                       help='Only process existing data, do not download')
    parser.add_argument('--visualize-only', action='store_true',
                       help='Only create visualizations from processed data')
    
    args = parser.parse_args()
    
    print("🌌 JWST Image Processing Pipeline")
    print("=" * 50)
    print(f"Target: {args.target}")
    print(f"Instrument: {args.instrument}")
    print(f"Max files: {args.max_files}")
    print()
    
    # Initialize components
    downloader = JWSTDataDownloader()
    processor = JWSTImageProcessor()
    visualizer = JWSTVisualizer()
    
    # Step 1: Download data (unless process-only or visualize-only)
    if not args.process_only and not args.visualize_only:
        print("📥 Step 1: Downloading JWST data...")
        print("-" * 30)
        
        # Search for observations
        observations = downloader.search_observations(
            target=args.target,
            instrument=args.instrument,
            max_records=args.max_files
        )
        
        if len(observations) == 0:
            print(f"No observations found for {args.target} with {args.instrument}")
            print("Trying with sample data...")
            downloaded_files = downloader.get_sample_data()
        else:
            # Download first observation
            obs_id = observations[0]['obsid']
            print(f"Downloading observation {obs_id}...")
            downloaded_files = downloader.download_observation(obs_id, max_files=args.max_files)
        
        if not downloaded_files:
            print("❌ No files downloaded. Exiting.")
            return
        
        print(f"✅ Downloaded {len(downloaded_files)} files")
        print()
    
    # Step 2: Process images (unless download-only or visualize-only)
    if not args.download_only and not args.visualize_only:
        print("🔧 Step 2: Processing JWST images...")
        print("-" * 30)
        
        # Find FITS files
        raw_dir = os.path.join(downloader.data_dir, "raw")
        fits_files = [f for f in os.listdir(raw_dir) if f.endswith('.fits')]
        
        if not fits_files:
            print("❌ No FITS files found for processing")
            return
        
        print(f"Found {len(fits_files)} FITS files to process")
        
        # Process files
        filepaths = [os.path.join(raw_dir, f) for f in fits_files]
        processed_filters = processor.process_multiple_filters(filepaths)
        
        if not processed_filters:
            print("❌ No files processed successfully")
            return
        
        print(f"✅ Processed {len(processed_filters)} filters")
        print()
    
    # Step 3: Create visualizations (unless download-only or process-only)
    if not args.download_only and not args.process_only:
        print("🎨 Step 3: Creating visualizations...")
        print("-" * 30)
        
        # Load processed data if not already available
        if 'processed_filters' not in locals():
            # Try to load from processed directory
            processed_dir = os.path.join(processor.data_dir, "processed")
            if os.path.exists(processed_dir):
                print("Loading previously processed data...")
                # This would require implementing a load function
                print("❌ No previously processed data found")
                return
            else:
                print("❌ No processed data available")
                return
        
        # Create individual filter plots
        for filter_name, result in processed_filters.items():
            if filter_name == 'composite':
                continue
            
            print(f"Creating plot for {filter_name}...")
            
            # Single image plot
            save_path = os.path.join(visualizer.output_dir, f"{filter_name}_single.png")
            visualizer.plot_single_image(
                result['enhanced_data'],
                title=f"JWST {args.target}",
                filter_name=filter_name,
                save_path=save_path
            )
            
            # Processing pipeline plot
            save_path = os.path.join(visualizer.output_dir, f"{filter_name}_pipeline.png")
            visualizer.plot_processing_pipeline(
                result['original_data'],
                result['calibrated_data'],
                result['denoised_data'],
                result['enhanced_data'],
                filter_name=filter_name,
                save_path=save_path
            )
            
            # Source detection plot (if sources were detected)
            if result['catalog'] is not None:
                save_path = os.path.join(visualizer.output_dir, f"{filter_name}_sources.png")
                visualizer.plot_source_catalog(
                    result['denoised_data'],
                    result['catalog'],
                    title=f"Source Detection - {filter_name}",
                    filter_name=filter_name,
                    save_path=save_path
                )
        
        # Create multi-filter plot
        if len(processed_filters) > 1:
            print("Creating multi-filter plot...")
            save_path = os.path.join(visualizer.output_dir, "multi_filter.png")
            visualizer.plot_multiple_filters(
                processed_filters,
                title=f"JWST {args.target} - Multi-Filter View",
                save_path=save_path
            )
        
        # Create RGB composite plot
        if 'composite' in processed_filters:
            print("Creating RGB composite plot...")
            composite = processed_filters['composite']
            save_path = os.path.join(visualizer.output_dir, "rgb_composite.png")
            visualizer.plot_rgb_composite(
                composite['rgb_data'],
                title=f"JWST {args.target} - RGB Composite",
                filters_used=composite['filters_used'],
                save_path=save_path
            )
        
        # Create publication-quality plot
        print("Creating publication-quality plot...")
        save_path = os.path.join(visualizer.output_dir, "publication_plot.png")
        visualizer.create_publication_plot(
            processed_filters,
            target_name=args.target,
            save_path=save_path
        )
        
        print(f"✅ Visualizations saved to {visualizer.output_dir}")
        print()
    
    print("🎉 Pipeline completed successfully!")
    print(f"📁 Data directory: {downloader.data_dir}")
    print(f"🖼️  Visualizations: {visualizer.output_dir}")

def run_example():
    """Run a simple example with sample data"""
    print("🌌 JWST Image Processing - Example Run")
    print("=" * 50)
    
    # Initialize components
    downloader = JWSTDataDownloader()
    processor = JWSTImageProcessor()
    visualizer = JWSTVisualizer()
    
    # Download sample data
    print("📥 Downloading sample JWST data...")
    downloaded_files = downloader.get_sample_data()
    
    if not downloaded_files:
        print("❌ No sample data downloaded")
        return
    
    # Process the data
    print("🔧 Processing images...")
    raw_dir = os.path.join(downloader.data_dir, "raw")
    fits_files = [f for f in os.listdir(raw_dir) if f.endswith('.fits')]
    filepaths = [os.path.join(raw_dir, f) for f in fits_files]
    
    processed_filters = processor.process_multiple_filters(filepaths)
    
    if not processed_filters:
        print("❌ No data processed")
        return
    
    # Create visualizations
    print("🎨 Creating visualizations...")
    
    # Create a simple plot for each filter
    for filter_name, result in processed_filters.items():
        if filter_name == 'composite':
            continue
        
        print(f"Plotting {filter_name}...")
        save_path = os.path.join(visualizer.output_dir, f"example_{filter_name}.png")
        visualizer.plot_single_image(
            result['enhanced_data'],
            title=f"JWST Example - {filter_name}",
            filter_name=filter_name,
            save_path=save_path
        )
    
    # Create RGB composite if available
    if 'composite' in processed_filters:
        composite = processed_filters['composite']
        save_path = os.path.join(visualizer.output_dir, "example_composite.png")
        visualizer.plot_rgb_composite(
            composite['rgb_data'],
            title="JWST Example - RGB Composite",
            filters_used=composite['filters_used'],
            save_path=save_path
        )
    
    print("✅ Example completed!")
    print(f"📁 Check the {visualizer.output_dir} directory for results")

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No arguments provided, run example
        run_example()
    else:
        # Run with command line arguments
        main()
