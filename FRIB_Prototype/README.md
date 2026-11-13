# Current FRIB project (Docker Version)

**Download [FRIBCURRENTPROJECT.zip](FRIBCURRENTPROJECT.zip)** using the download button or **View raw**, then extract it.
[FRIB_Final_Project.zip](https://github.com/user-attachments/files/34776321/FRIB_Final_Project.zip)

### Prerequisites
1. Download and install **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** for your operating system (Mac or Windows). 
2. Ensure Docker Desktop is running in the background before proceeding.

### Initial Setup & Launch
1. Open your terminal or command prompt and navigate directly into the extracted `FRIB_Final_Project` folder.
2. Build and start the infrastructure by running the following command. The very first launch will take several minutes as it downloads required dependencies and AI models:
   ```bash
   docker compose up -d --build
   
3. Open your web browser and navigate to http://localhost:8501 to access the ai wiki dashboard.
   
Note: Later launches will reuse the permanent local cache. Model weights, virtual environments, personal records, credentials, and runtime databases are excluded from the initial download.
