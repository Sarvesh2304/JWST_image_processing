#!/bin/bash

# Setup GitHub repository for JWST Image Processing Project

echo "🌌 Setting up GitHub repository for JWST Image Processing Project"
echo "=================================================================="

# Initialize git repository
echo "📁 Initializing git repository..."
git init

# Add all files
echo "📝 Adding files to git..."
git add .

# Create initial commit
echo "💾 Creating initial commit..."
git commit -m "🌌 Initial commit: JWST Image Processing Pipeline

✅ Features:
- Download real JWST data from MAST using astroquery
- Complete image processing pipeline (calibration, denoising, enhancement)
- Multi-filter support and RGB composite creation
- Source detection and professional visualizations
- Support for all JWST instruments (NIRCam, MIRI, NIRSpec, NIRISS)

✅ Successfully tested with real NIRISS observations (2048×2048 pixels)
✅ Generated 15+ professional visualizations
✅ Complete documentation and examples

Ready to explore the cosmos with real JWST data! 🚀"

echo "✅ Git repository initialized!"
echo ""
echo "🚀 Next steps:"
echo "1. Create a new repository on GitHub: https://github.com/new"
echo "2. Name it: jwst-image-processing"
echo "3. Don't initialize with README (we already have one)"
echo "4. Run these commands:"
echo ""
echo "   git remote add origin https://github.com/YOUR_USERNAME/jwst-image-processing.git"
echo "   git branch -M main"
echo "   git push -u origin main"
echo ""
echo "🌌 Your JWST project is ready for GitHub! ✨"
