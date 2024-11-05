#!/bin/bash

rshim -l 1 &  # Start rshim in the background

python3 /dpu-tools "$@"  # Pass any arguments to dpu-tools


