#!/bin/bash
echo "Downloading PLINK..."
wget https://s3.amazonaws.com/plink1-assets/plink_linux_x86_64_20231211.zip
unzip plink_linux_x86_64_20231211.zip
chmod +x plink
echo "PLINK installed successfully"