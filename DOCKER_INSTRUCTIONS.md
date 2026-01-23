# Docker Instructions for VMR Migration Tool

This project is containerized to ensure consistent execution across different environments and resolve Python version conflicts.

## Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop/) installed on your machine.
- A `.env` file in this directory with your credentials (see `.env.example` if available, or ask the project owner).

## One-Time Setup

1. **Build the Docker Image**
   This downloads the necessary Python version (3.10), installs dependencies, and the Chromium browser for automation.
   ```bash
   docker-compose build
   ```

## Running the Migration

1. **Start the Container**
   ```bash
   docker-compose up -d
   ```

2. **Run the Downloader (New Engine)**
   ```bash
   docker-compose exec vmr-migration python production_migration_engine_new.py
   ```
   The files will be downloaded to the `vmr_downloads` directory on your host machine.

3. **Run the Restructuring Tool**
   ```bash
   docker-compose exec vmr-migration python restructure_migration.py
   ```

## Notes

- **Headless Mode**: The scripts in the Docker container run in "headless" mode (no visible browser window). The `production_migration_engine_new.py` is already configured for this.
- **File Access**: The local directory is mounted to `/app` in the container. Any files created in `/app` (like downloads) will instantly appear in your local folder.
- **Dependencies**: Use `requirements-docker.txt` to manage dependencies for the Docker environment.

## Troubleshooting

- **Credentials**: Ensure your `.env` file is present and has the correct values. It is not copied into the image but is passed at runtime.
- **Permission Errors**: If you encounter file permission errors on Linux, verify the user ID matching. On Windows/Mac, Docker Desktop handles this automatically.
