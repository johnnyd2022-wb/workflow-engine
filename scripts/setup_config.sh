#!/bin/bash

# Setup script to initialize configuration files from templates

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to setup configuration files
setup_config() {
    print_status "Setting up configuration files..."
    
    # Check if config directory exists
    if [ ! -d "config" ]; then
        print_warning "Config directory not found. Creating it..."
        mkdir -p config
    fi
    
    # Copy templates to actual config files if they don't exist
    for env in local test prod; do
        if [ ! -f "config/${env}.ini" ]; then
            if [ -f "config/${env}.ini.template" ]; then
                cp "config/${env}.ini.template" "config/${env}.ini"
                print_success "Created config/${env}.ini from template"
            else
                print_warning "Template config/${env}.ini.template not found"
            fi
        else
            print_warning "config/${env}.ini already exists, skipping..."
        fi
    done
    
    print_success "Configuration setup completed!"
    print_warning "Please edit the config files with your actual values:"
    echo "  - config/local.ini"
    echo "  - config/test.ini" 
    echo "  - config/prod.ini"
    echo ""
    print_status "Important: Never commit the actual config files to Git!"
    print_status "Only the .template files should be committed."
}

# Run setup
setup_config
