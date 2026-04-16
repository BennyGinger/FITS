`git clone --recurse-submodules https://github.com/BennyGinger/FITS.git fits`

# to sync:
`git submodule sync --recursive` # update the remote URL of the submodule to match the URL specified in .gitmodules
`git submodule update --init --recursive` # set the submodule to the commit specified in the index of the parent repository
`git submodule update --remote --recursive` # set the submodule to the latest commit on the branch specified in .gitmodules

# to add a new submodule:
`git submodule add <repository_url> <path>` # add a new submodule at the specified path
`git commit -m "Add submodule"` # commit the change to the parent repository
