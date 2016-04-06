# this is for conda; if you use virtualenv, please adjust commands accordingly
source activate chgksuite; # replace `chgksuite` with your py2 env name
py.test;
source deactivate;
source activate 4s3; # replace `4s3` with your py3 env name
py.test;
source deactivate;