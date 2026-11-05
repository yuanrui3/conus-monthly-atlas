# Publish the CONUS Monthly Atlas on GitHub Pages

This package contains the static website and its data in `docs/`. Opening `docs/index.html` as a disk file is insufficient because the app fetches data over HTTP. No package manager, API keys, application server or geographic data rebuild is needed to host the bundled layers. Some local detail layers make requests to outside data providers; their availability depends on the provider and browser.

## From Windows PowerShell

1. Extract the complete ZIP into a new folder outside any Git repository. In that folder, open PowerShell. Install [Git](https://git-scm.com/downloads) and [GitHub CLI](https://cli.github.com/) if needed.
2. Sign in to your personal GitHub.com account in the browser and confirm the active login:

   ```powershell
   gh auth login --hostname github.com --git-protocol https --web
   gh api --hostname github.com user --jq .login
   ```

3. Run the publisher, replacing `YOUR-LOGIN` with the account name from step 2:

   ```powershell
   .\Publish-GitHubPages.ps1 -Owner YOUR-LOGIN
   ```

The script verifies the packaged files, creates a **public** repository called `conus-monthly-atlas` in that account, pushes the release, enables Pages on **main → /docs**, and prints the repository and Pages URLs. It waits up to two minutes for GitHub's published page to return the atlas title. If Pages is still building, see **Settings → Pages** and **Actions** in the new repository. It can be rerun from the same extraction after an interrupted deployment. It never force-pushes. It does not require entering a token in the script.

To choose another new repository name, add `-Repository your-name`. To publish to an already-created **empty** public repository under your account, add `-UseExistingEmpty` and, if necessary, `-Repository your-name`. Repositories with existing content are not accepted by the initial publisher. For future atlas updates, edit your repository normally, commit, and push to `main`; Pages republishes the files under `docs/`.

## Manual alternative, any OS

Extract into a new, otherwise empty folder. Create a new empty **public** repository on GitHub **without initializing a README, license or gitignore**. From the extracted folder, use Git or GitHub Desktop to commit **this folder's contents** and push them to its `main` branch. The committed tree should contain `docs/index.html`, `docs/.nojekyll`, `docs/data/`, `docs/vendor/` and the other release files. In GitHub, open **Settings → Pages → Build and deployment → Deploy from a branch**, select **main** and **/docs**, and save. Use the URL GitHub supplies in that panel. There is no need to copy any of the files into the domain root.

## Check the deployment

Open the Pages URL and switch between January and July in Overview. Open River flow (the URL accepts `#river-flow`) and select a gauge; change months to inspect its record. Check Slope and the seasonal snow and Great Lakes ice overlays. Test the local detail layers with a network connection: a working nationwide overview does not guarantee that all remote sources accept requests from this new origin. Data source or coverage gaps remain distinct from measured zero.

The ZIP's `release-manifest.json` lists byte lengths and SHA-256 hashes for every other release file. Data and app assets come from atlas v0.8, source revision `85ae48c`. The Pages export relocates the web root, includes the rebuilding and validation scripts, and removes prior hosting identifiers and private planning text from descriptive metadata. Original checks of provider access describe the earlier deployment. See the [atlas README](README.md) and the in-app Sources pane for geographic coverage, provenance and interpretation.

Official references: [GitHub Pages publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site), [GitHub Pages API](https://docs.github.com/en/rest/pages/pages), [GitHub CLI authentication](https://cli.github.com/manual/gh_auth_login).
