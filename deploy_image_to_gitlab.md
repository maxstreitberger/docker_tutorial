# Build, push and deploy a Docker image with GitLab CI/CD

Pipeline: **build → test → run → package (jar) → push image to the GitLab Container Registry → deploy to env-stage → deploy to env-prod (manual)**

New in this step: the **Dockerfile** and the **automatic deployment of the image to the environments**.


## Assumptions/Pre-requisites

1. The integration server and its Container Registry from [s3 registry-vm](../devops/pipeline/s3-automate-deploy/registry-vm/README.md) are up and running:
   - GitLab at `http://192.168.56.9/gitlab`, registry at `192.168.56.9:5050`
   - runners `docker` (docker executor, Maven jobs) and `registry-vm-shell` (shell executor, can run `docker`)
   - the Docker on integration-server trusts the insecure registry `192.168.56.9:5050`
2. The project `MavenHelloWorldProject` is pushed to GitLab and its Maven pipeline (build, test, run) runs.


## Overview

| VM | IP | Role | Runner (executor, tag) |
|---|---|---|---|
| integration-server | 192.168.56.9 | GitLab, Container Registry (`:5050`) | `docker` (docker, tag `docker`) + `registry-vm-shell` (shell, tag `registry-vm-shell`) |
| env-stage | 192.168.56.10 | staging | `env-stage` (shell, tag `stage-vm-shell`) |
| env-prod | 192.168.56.11 | production | `env-prod` (shell, tag `prod-vm-shell`) |

- env-stage / env-prod: `devops/pipeline/s1-create-skeleton/env-{stage,prod}`



## Prepare the environments (env-stage, env-prod)

1. In both Vagrantfiles, use a current box (the 16.04 box has a Docker that's too old, see issues below):

`config.vm.box = "ubuntu/jammy64"`

2. Install Docker and trust the registry via provisioning:

```
config.vm.provision "shell", inline: <<-SHELL
  apt-get update
  apt-get install -y default-jdk
  apt-get install -y docker.io
  usermod -aG docker vagrant
  echo '{ "insecure-registries": ["192.168.56.9:5050"] }' > /etc/docker/daemon.json
  systemctl restart docker
SHELL
```

3. Recreate the VMs:

`vagrant destroy -f && vagrant up`

4. Check on each VM:

`docker info | grep -A2 'Insecure Registries'` (lists `192.168.56.9:5050`)

`docker login 192.168.56.9:5050` (GitLab user)

*Possible issues:*

| Symptom | Cause | Fix |
|---|---|---|
| `docker: command not found` | provisioning still running | wait for `vagrant up` to finish |
| `permission denied … /var/run/docker.sock` | user just added to `docker` group, old session | log out/in (`exit`, `vagrant ssh`) or `newgrp docker` |



## Create the environment runners

Create each runner in GitLab first (**Settings → CI/CD → Runners → New project runner**, set the tag), then register it on the VM with the `glrt-…` token.

1. Install (on env-stage and env-prod):

`curl -L https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh | sudo bash`

`sudo apt-get install gitlab-runner`

2. Register:

`sudo gitlab-runner register`

URL: `http://192.168.56.9/gitlab/`, executor: `shell`

| VM | Tag |
|---|---|
| env-stage | `stage-vm-shell` |
| env-prod | `prod-vm-shell` |

3. Give gitlab-runner access to Docker:

`sudo usermod -aG docker gitlab-runner`

`sudo gitlab-runner restart`

`sudo -u gitlab-runner -H docker info`

4. Check the runners registered on a VM:

`sudo gitlab-runner list`

`sudo gitlab-runner verify` (`--delete` removes entries GitLab no longer knows)

*Notes:*<br>
- A job runs on **any** runner that has **all** of its tags. Each tag must be on exactly one runner.
- Leave "Run untagged jobs" off. All jobs have tags (via `default:`, see step 0).



## Extend the pipeline step by step

Add one step at a time to `.gitlab-ci.yml`, push, and check it before going on. The full file is in the [appendix](#appendix-full-gitlab-ciyml).


### Step 0: Starting point

The Maven pipeline from s2/s3. Make sure every job has a tag via `default:`, otherwise the Maven jobs stay *pending* once "Run untagged jobs" is off:

```
image: maven:latest

default:
  tags:
    - docker

stages:
  - build
  - test
  - run

cache:
  paths:
    - target/

build_app:
  stage: build
  script:
    - mvn compile

test_app:
  stage: test
  script:
    - mvn test

run_app:
  stage: run
  script:
    - mvn package
    - mvn exec:java -Dexec.mainClass="com.jcg.maven.App"
```

**Check:** **Build → Pipelines** shows build, test and run green.


### Step 1: Package the jar

1. Add `- package` to `stages:`.

2. Add the job:

```
package_app:
  stage: package
  script:
    - mvn package            # build the jar here instead of relying on the cache
  artifacts:
    name: "my-app"
    paths:
      - target/*.jar
```

*Notes:*<br>
- `artifacts:` stores the jar with the pipeline and passes it to later jobs.
- `cache:` is not suitable for this: it only speeds up runs and isn't guaranteed to be there.

**Check:** the jar can be downloaded from the job page or **Build → Artifacts**.


### Step 2: Build and push the image

1. Add a `Dockerfile` to the repo root (next to `pom.xml`):

```
FROM eclipse-temurin:21-jre
COPY target/*.jar /app/app.jar
CMD ["java", "-jar", "/app/app.jar"]
```

No fat jar needed: `mainClass` is in the manifest and JUnit is test-only.

2. Add `- push` to `stages:`.

3. Add the job:

```
docker_image:
  stage: push
  tags: [registry-vm-shell]
  needs: [package_app]
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" $CI_REGISTRY
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" -t "$CI_REGISTRY_IMAGE:latest" .
    - docker push --all-tags "$CI_REGISTRY_IMAGE"
```

*Notes:*<br>
- `tags: [registry-vm-shell]` overrides the default: this job needs the shell runner with access to Docker.
- `needs: [package_app]` downloads the jar artifact into the job, so `COPY target/*.jar` finds it.
- `$CI_REGISTRY*` variables are provided by GitLab. Nothing to configure.
- The image is tagged with the commit SHA (exact version) and `latest`.

**Check:** **Deploy → Container Registry** shows the image with the SHA and `latest` tags.

Test it manually on env-stage or env-prod:

`docker run --rm 192.168.56.9:5050/test/mavenhelloworldproject:latest` (prints `Hello World!`)

*Possible issues:*

| Symptom | Cause | Fix |
|---|---|---|
| `pthread_create failed (EPERM)` / `Failed to create worker thread` | Docker 18.09 on Ubuntu 16.04 blocks `clone3` (seccomp), used by new glibc in `eclipse-temurin:21` | switch env VMs to `ubuntu/jammy64` (Docker 29). Quick test only: `--security-opt seccomp=unconfined` |


### Step 3: Deploy to stage

1. Add `- deploy-stage` to `stages:`.

2. Add the job:

```
deploy_stage:
  stage: deploy-stage
  tags: [stage-vm-shell]
  needs: [docker_image]
  variables:
    GIT_STRATEGY: none       # deploy only needs the image, not the source
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" $CI_REGISTRY
    - docker pull "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
    - docker run --rm "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  environment:
    name: staging
```

*Notes:*<br>
- `tags: [stage-vm-shell]` makes the job run on env-stage.
- Pulling `$CI_COMMIT_SHORT_SHA` (not `latest`) deploys exactly the image of this pipeline.
- `environment:` makes GitLab track what is deployed where (**Operate → Environments**).

**Check:** the job log starts with `on env-stage …` and ends with `Hello World!`. On env-stage, `docker images` lists `…:<sha>`.

*Possible issues:*

| Symptom | Cause | Fix |
|---|---|---|
| Job stuck in *pending* | no runner with the tag `stage-vm-shell` | check runner tags in **Settings → CI/CD → Runners** |
| Job ran on env-prod | two runners had the tag `stage-vm-shell` | one tag per runner. The job log line `on <runner>` shows who ran it |
| `permission denied … /var/run/docker.sock` in the job | gitlab-runner not in `docker` group, or runner not restarted | `sudo usermod -aG docker gitlab-runner && sudo gitlab-runner restart` |
| Old runner still in `config.toml` | runner deleted/recreated in GitLab | `sudo gitlab-runner verify --delete` |


### Step 4: Deploy to prod (manual)

1. Add `- deploy-prod` to `stages:`.

2. Add the job:

```
deploy_prod:
  stage: deploy-prod
  tags: [prod-vm-shell]
  needs: [deploy_stage]
  when: manual
  variables:
    GIT_STRATEGY: none
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" $CI_REGISTRY
    - docker pull "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
    - docker run --rm "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  environment:
    name: production
```

*Notes:*<br>
- `when: manual` goes on the job level: prod is deployed only after clicking ▶ on `deploy_prod`.
- `needs: [deploy_stage]` → prod only gets versions that made it through stage.

**Check:**
1. **Build → Pipelines**: all jobs green, `deploy_prod` waits with ▶. Click it.
2. The job log starts with `on env-prod …` and ends with `Hello World!`.
3. **Operate → Environments** lists `staging` and `production` with the deployed commit.



## Rollback

**Operate → Environments → production → Rollback** re-runs the `deploy_prod` job of an older pipeline, so it pulls and runs that pipeline's SHA image. Manually on the VM: `docker run --rm 192.168.56.9:5050/test/mavenhelloworldproject:<old-sha>`.

*Note:* the hello-world app exits right away, so after a deploy/rollback nothing stays running (`docker ps` is empty). The output is in the job log.

*Possible issues:*

| Symptom | Cause | Fix |
|---|---|---|
| "An error occurred while rolling back the environment" | rollback retries the old `deploy_prod` job; that job had never run (still *manual*) | play ▶ `deploy_prod` in the old pipeline. Rollback only works to versions that were actually deployed |



## General issues

| Symptom | Cause | Fix |
|---|---|---|
| GitLab slow/unreachable, integration-server in state `gurumeditation` | host overloaded with all VMs running (GitLab wants ≥ 8 GB) | `vagrant halt --force && vagrant up`. More RAM for integration-server (e.g. 10 GB) + `vagrant reload` |



## Next steps

- Multi-stage Dockerfile (build the jar inside `docker build`) instead of the artifact handoff
- Rollback with Kubernetes: `kubectl rollout undo`



## Appendix: full .gitlab-ci.yml

<details>
<summary>Show the full file</summary>

```
image: maven:latest

default:
  tags:
    - docker

stages:
  - build
  - test
  - run
  - package
  - push
  - deploy-stage
  - deploy-prod

cache:
  paths:
    - target/

build_app:
  stage: build
  script:
    - mvn compile

test_app:
  stage: test
  script:
    - mvn test

run_app:
  stage: run
  script:
    - mvn package
    - mvn exec:java -Dexec.mainClass="com.jcg.maven.App"

package_app:
  stage: package
  script:
    - mvn package            # build the jar here instead of relying on the cache
  artifacts:
    name: "my-app"
    paths:
      - target/*.jar

docker_image:
  stage: push
  tags: [registry-vm-shell]
  needs: [package_app]
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" $CI_REGISTRY
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" -t "$CI_REGISTRY_IMAGE:latest" .
    - docker push --all-tags "$CI_REGISTRY_IMAGE"

deploy_stage:
  stage: deploy-stage
  tags: [stage-vm-shell]
  needs: [docker_image]
  variables:
    GIT_STRATEGY: none       # deploy only needs the image, not the source
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" $CI_REGISTRY
    - docker pull "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
    - docker run --rm "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  environment:
    name: staging

deploy_prod:
  stage: deploy-prod
  tags: [prod-vm-shell]
  needs: [deploy_stage]
  when: manual
  variables:
    GIT_STRATEGY: none
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" $CI_REGISTRY
    - docker pull "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
    - docker run --rm "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  environment:
    name: production
```

</details>
