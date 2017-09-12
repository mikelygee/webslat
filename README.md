WebSLAT is a web-based interface to the [OpenSLAT](http://github.com/mikelygee/SLAT) project. The procedure below
will create a VirtualBox image including the OpenSLAT libraries and WebSLAT
served via Apache.

1.  Run `virtualbox`.
2.  Click `New`, then `Expert Mode` (if not already active).
3.  Fill out the form:
    
    -   **Name:** WebSLAT
    -   **Type:** Linux
    -   **Version:** Debian (64-bit)
    -   **Memory Size:** 1024 MB
    -   'Create a virtual hard disk now'
    
    Then click `Create`
4.  Specify:
    
    -   **File Location:** `/home/mag109/VirtualBox VMs/WebSLAT/WebSLAT.vdi`
    -   **File size:** `8.00 GB`
    -   **Hard disk file type:** `VDI (VirtualBox Disk Image)`
    -   **Storage on physical hard disk:** `Dynamically allocated`
    
    Then click `Create`
5.  Enable port forwarding:
    -   host port 3022 to VM port 22    # For ssh
    -   host port 3080 to VM port 8000  # For server
6.  Power on the VM. Boot from `~/Downloads/debian-9.0.0-amd64-netinst.iso`. Run
    the graphical installer.
    
    -   **hostname:** WebSLAT
    -   **domain:** webslat.org
    -   **root password:** webslat-admin
    -   **user name & password:** webslat-user
    
    Install standard system utilities and SSH server, but no desktop environment.
7.  Set up a key for ssh logins:
    
        # Create an ssh key, without a password, for 
        # communicating with the VM:
        if [[ ! -e ~/.ssh/vm ]]; then
            ssh-keygen -f ~/.ssh/vm -N ''
        fi
        
        # If we've used the key with an earlier VM,
        # remove it:
        ssh-keygen -f "/home/mag109/.ssh/known_hosts" \
        	   -R [127.0.0.1]:3022
        
        # Install the key in the VM:
        ssh-copy-id -o "StrictHostKeyChecking no" \
        	    -i ~/.ssh/vm \
        	    -p 3022 webslat-user@127.0.0.1

8.  Run these commands on the VM as root. (I can't figure out how to do this from
    a script on the host machine).
    
    This will install the packages needed to build and run `OpenSLAT`:
    
        apt-get update
        apt-get -y install  git \
            make \
            pkg-config \
            libgsl-dev \
            python3-dev \
            python3-pip \
            g++ \
            libboost-dev \
            libboost-log-dev \
            libboost-test-dev \
            swig3.0 \
            openjdk-8-jre-headless \
            curl \
            zile
        curl \
            http://www.antlr.org/download/antlr-4.7-complete.jar \
            -o /usr/local/lib/antlr-4.7-complete.jar
        
        ln -s /usr/bin/swig3.0 /usr/bin/swig
        
        pip3 install antlr4-python3-runtime numpy typing
9.  Build the libraries:
    
        echo \
             'if [[ -e SLAT ]]; then
        	  cd SLAT/linux
        	  git pull
              else
        	  git clone \
        	  http://github.com/mikelygee/SLAT
        	  cd SLAT/linux
              fi;
              make' |
             ssh -i ~/.ssh/vm -p 3022 \
        	 webslat-user@127.0.0.1 |
             tail -5
10. Add the search paths to `.bashrc`, if they aren't already there;
    
        echo \
            "if ! grep PYTHONPATH .profile; then
        	 echo export LD_LIBRARY_PATH=~/SLAT/linux/lib >> .profile
        	 echo export PYTHONPATH=~/SLAT/linux/lib >> .profile
             fi
        " | ssh -i ~/.ssh/vm -p 3022 webslat-user@127.0.0.1 | tail -5

11. Run the unit tests:
    
        echo "cd SLAT/linux/bin
               ./unit_tests
        " | ssh -i ~/.ssh/vm -p 3022 \
        	webslat-user@127.0.0.1 2>&1 | tail -5

1.  Run the C++ example2 binary:
    
        echo "cd SLAT/parser/example2
        	 ../../linux/bin/example2
        " | ssh -i ~/.ssh/vm -p 3022 \
        	webslat-user@127.0.0.1 2>&1 | tail -5
2.  Run the example2 Python script:
    
        echo "cd SLAT/parser/example2
        	 ./example2.py
        " | ssh -i ~/.ssh/vm -p 3022 \
        	webslat-user@127.0.0.1 2>&1 | tail -5

1.  Run the example2 SLAT script:
    
        echo "cd SLAT/parser/example2
        	 ../../linux/scripts/SlatInterpreter.py \
        	      example2.slat
        " | ssh -i ~/.ssh/vm -p 3022 \
        	webslat-user@127.0.0.1 2>&1 | tail -10

2.  Run these commands on the VM as root. (I can't figure out how to do this from
    a script on the host machine).
    
    This will install the packages needed for `WebSLAT`:
    
        apt-get -y install gfortran \
        	gsl-bin \
        	liblapack-dev \
        	libfreetype6-dev \
        	python3-tk \
        	links2
        pip3 install virtualenv
3.  Set up a virtual python environment
    
        echo "virtualenv webslat-env
        	 source webslat-env/bin/activate
        	 pip3 install numpy \
        	     matplotlib \
        	     scipy \
        	     django \
        	     django-graphos
        	 deactivate
        " | ssh -i ~/.ssh/vm -p 3022 \
        	webslat-user@127.0.0.1 2>&1 | tail -10

1.  Copy the `webslat` files to the VM, since they aren't yet on `github`:
    
        echo "git clone \
        	  http://github.com/mikelygee/webslat
        " | ssh -i ~/.ssh/vm -p 3022 \
        	webslat-user@127.0.0.1 2>&1 | tail -10
2.  Copy the `graphos` templates to the `slat` directory:
    
        echo "cd .local/lib/python3.5/site-packages/graphos/templates
              cp -r graphos/ ~/webslat/webslat/slat/templates
        " | ssh -i ~/.ssh/vm -p 3022 \
        	webslat-user@127.0.0.1 2>&1 | tail -10

1.  Test the `django` server:
    As `webslat-user` on the VM, run:
    
        source webslat-env/bin/activate
        cd webslat/webslat
        python3 manage.py migrate
        python3 manage.py runserver 0:8000
    
    In a separate session, run:
    
        links2 127.0.0.1:8000/slat
    
    to confirm the server is working.
    
    Quit `links2` and kill the server.
2.  User `apache2` to serve `webslat`. First, as `root` on the VM, run:
    
        apt-get -y install apache2 \
            libapache2-mod-wsgi-py3
3.  Make sure the `apache2` process can read the database file.
    1.  Assign appropriate permissions:
        
            echo "chmod 664 webslat/webslat/db.sqlite3
                  chmod 775 webslat/webslat
            " | ssh -i ~/.ssh/vm -p 3022 webslat-user@127.0.0.1 2>&1 | tail -10

1.  Assign the files to the `www-data` group. As root on the VM, run:
    
        chown :www-data /home/webslat-user/webslat/webslat/db.sqlite3
        chown :www-data /home/webslat-user/webslat/webslat

1.  Edit `webslat/webslat/webslat/settings.py`
    1.  Set:
        
            ALLOWED_HOSTS = ['localhost', '127.0.0.1', '127.0.1.1']
    2.  Set:
        
            STATIC_ROOT = os.path.join(BASE_DIR, 'static/')
2.  Create the static files:
    
        echo "source webslat-env/bin/activate
              cd webslat/webslat
             ./manage.py collectstatic
        " | ssh -i ~/.ssh/vm -p 3022 webslat-user@127.0.0.1 2>&1 | tail -10

3.  As `root` on the VM, edit `/etc/apache2/sites-available/000-default.conf`, by
    adding, inside the `<VirtualHost...>` tag:
    
          Alias /static /home/webslat-user/webslat/webslat/static
          <Directory /home/webslat-user/webslat/webslat/static>
            Require all granted
          </Directory>
        
          <Directory /home/webslat-user/webslat/webslat/webslat>
            <Files wsgi.py>
        	Require all granted
            </Files>
        </Directory>
        
        WSGIDaemonProcess webslat python-home=/home/webslat-user/webslat-env python-path=/home/webslat-user/webslat/webslat:/home/webslat-user/SLAT/linux/lib
        WSGIProcessGroup webslat
        WSGIScriptAlias / /home/webslat-user/webslat/webslat/webslat/wsgi.py
    
    As `root`, run:
    
        apache2ctl configtest
    
    to check the configuration file.
4.  Install `libslat` where `apache2` can find it. As `root`, on the VM, run:
    
        ln -s /home/webslat-user/SLAT/linux/lib/libslat.so /usr/local/lib
        ldconfig
5.  Restart the server. As `root`, on the VM, run:
    
        systemctl restart apache2

To update OpenSLAT and WebSLAT without creating a new image:

1.  Update OpenSLAT from git, and build:
    
        echo \
            'cd SLAT/linux
             git pull
             make' |
             ssh -i ~/.ssh/vm -p 3022 \
        	 webslat-user@127.0.0.1 |
             tail -5

2.  Update WebSLAT:
    
        echo \
            'cd webslat
             git pull
             ' |
             ssh -i ~/.ssh/vm -p 3022 \
        	 webslat-user@127.0.0.1 |
             tail -5

3.  Run migrations:
    
        echo "source webslat-env/bin/activate
              cd webslat/webslat
             yes yes | ./manage.py migrate
        " | ssh -i ~/.ssh/vm -p 3022 webslat-user@127.0.0.1 2>&1 | tail -10

4.  Update the static files:
    
        echo "source webslat-env/bin/activate
              cd webslat/webslat
             yes yes | ./manage.py collectstatic
        " | ssh -i ~/.ssh/vm -p 3022 webslat-user@127.0.0.1 2>&1 | tail -10

5.  Restart the server. As `root`, on the VM, run:
    
        systemctl restart apache2

