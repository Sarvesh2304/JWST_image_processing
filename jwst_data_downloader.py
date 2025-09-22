"""
JWST Data Downloader
Downloads James Webb Space Telescope data from MAST (Mikulski Archive for Space Telescopes)
"""

import os
import requests
import json
from astropy.io import fits
from astropy.table import Table
import numpy as np
from typing import List, Dict, Optional
import time

class JWSTDataDownloader:
    """Download JWST data from MAST archive"""
    
    def __init__(self, data_dir: str = "jwst_data"):
        self.data_dir = data_dir
        self.mast_url = "https://mast.stsci.edu/api/v0.1/Download/file"
        self.search_url = "https://mast.stsci.edu/api/v0.1/Invoke/Mast.Caom.Cone"
        
        # Create data directory
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(os.path.join(data_dir, "raw"), exist_ok=True)
        os.makedirs(os.path.join(data_dir, "processed"), exist_ok=True)
    
    def search_observations(self, 
                          target: str = "NGC 3132", 
                          instrument: str = "NIRCam",
                          filters: List[str] = None,
                          max_records: int = 10) -> Table:
        """
        Search for JWST observations
        
        Parameters:
        -----------
        target : str
            Target name (e.g., "NGC 3132", "M51", "Stephan's Quintet")
        instrument : str
            JWST instrument ("NIRCam", "NIRSpec", "MIRI", "NIRISS")
        filters : list
            List of filters to search for
        max_records : int
            Maximum number of records to return
        """
        
        # Default filters for different instruments
        if filters is None:
            if instrument == "NIRCam":
                filters = ["F090W", "F150W", "F200W", "F277W", "F356W", "F444W"]
            elif instrument == "MIRI":
                filters = ["F560W", "F770W", "F1000W", "F1130W", "F1280W", "F1500W", "F1800W", "F2100W", "F2550W"]
            else:
                filters = []
        
        # Search parameters
        search_params = {
            "service": "Mast.Caom.Cone",
            "params": {
                "ra": 0,  # Will be resolved by target name
                "dec": 0,
                "radius": 0.1,
                "target": target,
                "instrument": instrument,
                "maxRecords": max_records
            },
            "format": "json"
        }
        
        try:
            response = requests.post(self.search_url, json=search_params)
            response.raise_for_status()
            data = response.json()
            
            if 'data' in data and len(data['data']) > 0:
                # Convert to astropy table
                table = Table(data['data'])
                print(f"Found {len(table)} observations for {target} with {instrument}")
                return table
            else:
                print(f"No observations found for {target} with {instrument}")
                return Table()
                
        except Exception as e:
            print(f"Error searching observations: {e}")
            return Table()
    
    def download_file(self, obs_id: str, filename: str) -> bool:
        """
        Download a single file from MAST
        
        Parameters:
        -----------
        obs_id : str
            Observation ID
        filename : str
            Filename to download
        """
        
        params = {
            "uri": f"mast:JWST/product/{filename}",
            "filename": filename
        }
        
        try:
            response = requests.get(self.mast_url, params=params, stream=True)
            response.raise_for_status()
            
            # Save file
            filepath = os.path.join(self.data_dir, "raw", filename)
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"Downloaded: {filename}")
            return True
            
        except Exception as e:
            print(f"Error downloading {filename}: {e}")
            return False
    
    def download_observation(self, obs_id: str, max_files: int = 5) -> List[str]:
        """
        Download all files for an observation
        
        Parameters:
        -----------
        obs_id : str
            Observation ID
        max_files : int
            Maximum number of files to download
        """
        
        # Search for files in this observation
        search_params = {
            "service": "Mast.Caom.Cone",
            "params": {
                "obsid": obs_id,
                "maxRecords": max_files
            },
            "format": "json"
        }
        
        try:
            response = requests.post(self.search_url, json=search_params)
            response.raise_for_status()
            data = response.json()
            
            downloaded_files = []
            
            if 'data' in data and len(data['data']) > 0:
                for record in data['data']:
                    if 'productFilename' in record:
                        filename = record['productFilename']
                        if self.download_file(obs_id, filename):
                            downloaded_files.append(filename)
                        time.sleep(1)  # Be nice to the server
            
            return downloaded_files
            
        except Exception as e:
            print(f"Error downloading observation {obs_id}: {e}")
            return []
    
    def get_sample_data(self) -> List[str]:
        """
        Download some sample JWST data for testing
        """
        print("Downloading sample JWST data...")
        
        # Some famous JWST targets
        sample_targets = [
            ("NGC 3132", "NIRCam"),  # Southern Ring Nebula
            ("M51", "NIRCam"),       # Whirlpool Galaxy
            ("NGC 3324", "NIRCam"),  # Cosmic Cliffs
        ]
        
        downloaded_files = []
        
        for target, instrument in sample_targets:
            print(f"\nSearching for {target} with {instrument}...")
            observations = self.search_observations(target, instrument, max_records=2)
            
            if len(observations) > 0:
                # Download first observation
                obs_id = observations[0]['obsid']
                files = self.download_observation(obs_id, max_files=3)
                downloaded_files.extend(files)
        
        return downloaded_files

# Example usage
if __name__ == "__main__":
    downloader = JWSTDataDownloader()
    
    # Download sample data
    files = downloader.get_sample_data()
    print(f"\nDownloaded {len(files)} files total")
