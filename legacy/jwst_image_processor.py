"""
JWST Image Processor
Processes and enhances James Webb Space Telescope images
"""

import os
import numpy as np
from astropy.io import fits
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats
from photutils.segmentation import detect_sources
from photutils.segmentation import SourceCatalog
from scipy import ndimage
from scipy.ndimage import gaussian_filter
from skimage import exposure, filters
from skimage.restoration import denoise_tv_chambolle
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, PowerNorm
import warnings
warnings.filterwarnings('ignore')

class JWSTImageProcessor:
    """Process and enhance JWST images"""
    
    def __init__(self, data_dir: str = "jwst_data"):
        self.data_dir = data_dir
        self.processed_dir = os.path.join(data_dir, "processed")
        os.makedirs(self.processed_dir, exist_ok=True)
    
    def load_fits_file(self, filepath: str) -> tuple:
        """
        Load FITS file and extract data, header, and WCS
        
        Parameters:
        -----------
        filepath : str
            Path to FITS file
            
        Returns:
        --------
        data : numpy.ndarray
            Image data
        header : astropy.io.fits.header.Header
            FITS header
        wcs : astropy.wcs.WCS
            World Coordinate System
        """
        try:
            with fits.open(filepath) as hdul:
                # JWST data is usually in the first HDU
                hdu = hdul[0]
                data = hdu.data
                header = hdu.header
                
                # Create WCS from header
                wcs = WCS(header)
                
                print(f"Loaded {filepath}")
                print(f"Data shape: {data.shape}")
                print(f"Data type: {data.dtype}")
                print(f"Data range: {np.nanmin(data):.2e} to {np.nanmax(data):.2e}")
                
                return data, header, wcs
                
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
            return None, None, None
    
    def basic_calibration(self, data: np.ndarray, header: dict) -> np.ndarray:
        """
        Apply basic calibration steps
        
        Parameters:
        -----------
        data : numpy.ndarray
            Raw image data
        header : dict
            FITS header
            
        Returns:
        --------
        calibrated_data : numpy.ndarray
            Calibrated image data
        """
        calibrated_data = data.copy()
        
        # Remove NaN and infinite values
        calibrated_data = np.nan_to_num(calibrated_data, nan=0.0, posinf=0.0, neginf=0.0)
        
        # Apply basic background subtraction
        mean, median, std = sigma_clipped_stats(calibrated_data, sigma=3.0)
        calibrated_data = calibrated_data - median
        
        # Remove negative values
        calibrated_data = np.maximum(calibrated_data, 0)
        
        return calibrated_data
    
    def enhance_contrast(self, data: np.ndarray, method: str = 'log') -> np.ndarray:
        """
        Enhance image contrast
        
        Parameters:
        -----------
        data : numpy.ndarray
            Image data
        method : str
            Enhancement method ('log', 'sqrt', 'power', 'histogram')
            
        Returns:
        --------
        enhanced_data : numpy.ndarray
            Enhanced image data
        """
        # Normalize to 0-1 range
        data_norm = (data - np.min(data)) / (np.max(data) - np.min(data))
        
        if method == 'log':
            # Logarithmic scaling
            enhanced_data = np.log1p(data_norm * 1000) / np.log(1001)
        elif method == 'sqrt':
            # Square root scaling
            enhanced_data = np.sqrt(data_norm)
        elif method == 'power':
            # Power law scaling (gamma correction)
            enhanced_data = np.power(data_norm, 0.5)
        elif method == 'histogram':
            # Histogram equalization
            enhanced_data = exposure.equalize_hist(data_norm)
        else:
            enhanced_data = data_norm
        
        return enhanced_data
    
    def denoise_image(self, data: np.ndarray, method: str = 'gaussian') -> np.ndarray:
        """
        Denoise image using various methods
        
        Parameters:
        -----------
        data : numpy.ndarray
            Image data
        method : str
            Denoising method ('gaussian', 'median', 'tv')
            
        Returns:
        --------
        denoised_data : numpy.ndarray
            Denoised image data
        """
        if method == 'gaussian':
            # Gaussian filter
            denoised_data = gaussian_filter(data, sigma=1.0)
        elif method == 'median':
            # Median filter
            denoised_data = ndimage.median_filter(data, size=3)
        elif method == 'tv':
            # Total variation denoising
            denoised_data = denoise_tv_chambolle(data, weight=0.1)
        else:
            denoised_data = data
        
        return denoised_data
    
    def detect_sources(self, data: np.ndarray, threshold: float = 3.0) -> SourceCatalog:
        """
        Detect sources in the image
        
        Parameters:
        -----------
        data : numpy.ndarray
            Image data
        threshold : float
            Detection threshold in sigma
            
        Returns:
        --------
        catalog : photutils.segmentation.SourceCatalog
            Source catalog
        """
        # Calculate background and noise
        mean, median, std = sigma_clipped_stats(data, sigma=3.0)
        
        # Detect sources
        threshold_value = median + threshold * std
        segment_map = detect_sources(data, threshold_value, npixels=5)
        
        if segment_map is not None:
            catalog = SourceCatalog(data, segment_map)
            print(f"Detected {len(catalog)} sources")
            return catalog
        else:
            print("No sources detected")
            return None
    
    def create_color_composite(self, 
                             red_data: np.ndarray, 
                             green_data: np.ndarray, 
                             blue_data: np.ndarray,
                             red_filter: str = "F444W",
                             green_filter: str = "F277W", 
                             blue_filter: str = "F090W") -> np.ndarray:
        """
        Create RGB color composite from three filter images
        
        Parameters:
        -----------
        red_data, green_data, blue_data : numpy.ndarray
            Image data for each filter
        red_filter, green_filter, blue_filter : str
            Filter names for labeling
            
        Returns:
        --------
        rgb_image : numpy.ndarray
            RGB composite image (H, W, 3)
        """
        # Normalize each channel
        def normalize_channel(data):
            data_norm = (data - np.percentile(data, 1)) / (np.percentile(data, 99) - np.percentile(data, 1))
            return np.clip(data_norm, 0, 1)
        
        red_norm = normalize_channel(red_data)
        green_norm = normalize_channel(green_data)
        blue_norm = normalize_channel(blue_data)
        
        # Create RGB array
        rgb_image = np.stack([red_norm, green_norm, blue_norm], axis=2)
        
        print(f"Created RGB composite: {red_filter} (R), {green_filter} (G), {blue_filter} (B)")
        
        return rgb_image
    
    def process_single_image(self, 
                           filepath: str, 
                           enhance_method: str = 'log',
                           denoise_method: str = 'gaussian',
                           detect_sources_flag: bool = True) -> dict:
        """
        Process a single JWST image
        
        Parameters:
        -----------
        filepath : str
            Path to FITS file
        enhance_method : str
            Contrast enhancement method
        denoise_method : str
            Denoising method
        detect_sources_flag : bool
            Whether to detect sources
            
        Returns:
        --------
        result : dict
            Dictionary containing processed data and metadata
        """
        # Load data
        data, header, wcs = self.load_fits_file(filepath)
        if data is None:
            return None
        
        # Basic calibration
        calibrated_data = self.basic_calibration(data, header)
        
        # Denoise
        denoised_data = self.denoise_image(calibrated_data, method=denoise_method)
        
        # Enhance contrast
        enhanced_data = self.enhance_contrast(denoised_data, method=enhance_method)
        
        # Detect sources
        catalog = None
        if detect_sources_flag:
            catalog = self.detect_sources(denoised_data)
        
        # Get filter information
        filter_name = header.get('FILTER', 'Unknown')
        instrument = header.get('INSTRUME', 'Unknown')
        
        result = {
            'original_data': data,
            'calibrated_data': calibrated_data,
            'denoised_data': denoised_data,
            'enhanced_data': enhanced_data,
            'catalog': catalog,
            'header': header,
            'wcs': wcs,
            'filter_name': filter_name,
            'instrument': instrument,
            'filename': os.path.basename(filepath)
        }
        
        return result
    
    def process_multiple_filters(self, 
                               filepaths: list, 
                               filters: list = None) -> dict:
        """
        Process multiple filter images and create composite
        
        Parameters:
        -----------
        filepaths : list
            List of FITS file paths
        filters : list
            List of filter names (optional)
            
        Returns:
        --------
        result : dict
            Dictionary containing processed data for all filters
        """
        processed_filters = {}
        
        for i, filepath in enumerate(filepaths):
            if not os.path.exists(filepath):
                print(f"File not found: {filepath}")
                continue
            
            print(f"\nProcessing filter {i+1}/{len(filepaths)}: {filepath}")
            result = self.process_single_image(filepath)
            
            if result is not None:
                filter_name = result['filter_name']
                processed_filters[filter_name] = result
        
        # Create composite if we have multiple filters
        if len(processed_filters) >= 3:
            filter_names = list(processed_filters.keys())
            print(f"\nCreating composite from filters: {filter_names}")
            
            # Use the first three filters for RGB
            rgb_data = self.create_color_composite(
                processed_filters[filter_names[0]]['enhanced_data'],
                processed_filters[filter_names[1]]['enhanced_data'],
                processed_filters[filter_names[2]]['enhanced_data'],
                filter_names[0], filter_names[1], filter_names[2]
            )
            
            processed_filters['composite'] = {
                'rgb_data': rgb_data,
                'filters_used': filter_names[:3]
            }
        
        return processed_filters

# Example usage
if __name__ == "__main__":
    processor = JWSTImageProcessor()
    
    # Process a single file (if available)
    raw_dir = os.path.join(processor.data_dir, "raw")
    if os.path.exists(raw_dir):
        files = [f for f in os.listdir(raw_dir) if f.endswith('.fits')]
        if files:
            filepath = os.path.join(raw_dir, files[0])
            result = processor.process_single_image(filepath)
            if result:
                print(f"Processed {result['filename']} with {result['filter_name']} filter")
