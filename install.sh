#!/bin/bash

echo_usage() {
  echo -e "Usage:"
  echo -e " $(basename "$0") [-h|--help]"
  echo -e " $(basename "$0") -i|--install -p|--package "
  echo -e "\t -i|--install      install requirements"
  echo -e "\t -p|--package      create package for AWS lambda"
  echo -e "\t -h|--help         print this help menu \n"
}

install_requirements() {
    echo "Instaling required python packages"
    pip3 install awscli boto3 cronex --user --upgrade 
}

create_awslambda_package() {
    echo "Creating zip file for lambda"
    mkdir packages
    pip3 install cronex --system --target packages
    cp EC2Scheduler/EC2Scheduler.py packages/lambda_function.py
    cd packages
    zip -r9 ../lambda_package.zip *
    cd ..
    rm -rf packages
    echo "Archive is ready $(pwd)/lambda_package.zip"
}

# TESTOVANI A ZPRACOVANI PARAMETRU
if [[ ("$#" -eq 0) || ("$#" -ne 1) ]]; then
    echo_usage
    exit 1
fi

case "$1" in
  -i|--install)
    install_requirements
    shift 2
    ;;
  -p|--package)
    create_awslambda_package
    shift 2
    ;;
  -h|--help)
    echo_usage
    exit 0
    ;;
  *)
    echo "Error: Unknown option: $1" >&2
    exit 1
    ;;
esac
