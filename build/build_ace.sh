#!/bin/bash

cd ace

    if [[ "$1" == "dev" ]]
    then 
        echo "Build APPIAN ACE DEV"
        docker build --no-cache . --target $1 --tag ace/appian:dev
    elif [[ "$1" == "prod" ]]
    then
        echo "Build APPIAN ACE PROD"
        docker build --no-cache . --target $1 --tag ace/appian:latest
    else
        echo "bad input $1, specify either dev or prod"
        exit -1
    fi
cd ..