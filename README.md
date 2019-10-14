# EC2 scheduler
Scheduling script for AWS EC2 instances and autoscaling groups by Lambda.

## Prerequisities
 - Set tags to instances and autoscaling groups
 - create IAM role for lambda
 - set lambda environment variables

## Create IAM role
1. Select IAM module
2. Click on "Create new role"
3. Choose lambda and click to "Next:Permissions"
4. Select AmazonEC2FullAccess and AutoScalingFullAccess 
5. Click on Next:Review
6. Fill role name and finish

## Create Lambda function
1. Select Lambda module
2. Click on Create function.
3. Select option "Author from scratch" fill function name "EC2Scheduler". 
4. Select runtime - Python 3.6
5. Select "Use an existing role" and choose role from previous step. 
6. Click on "Create function"
7. Upload zip file with function and libraries

## Working tags
### RUN:DAYS
List of instance working days 
[MON,TUE,WED,THU,FRI,SAT,SUN]
### RUN:HOURS
Time definition in format START_HOUR-STOP-HOUR
```
01:00-20:00
06:00-17:00
...
```
### OFFPEAK
Only for autoscaling groups
Number of instances running out of working hours. 

### Special ussage
RUN:DAYS or RUN:HOURS fill "manual" - with this value scheduler will ignore scheduling setings

RUN:HOURS - 06:00-01:00 set running hours 00:00 to 01:00 and 06:00 to 23:59

OFFPEAK = -1 - Affects ASG group with disabling HealtCheck. With this settings u can stop instance in ASG without terminating.

## Lambda environment variables for security scan
```
secureScanDay - Day in month (number) or day of week (0#1 first sunday in month)
secureScanDuration - number in hours
secureScanStartTime - number in hours
```

## Lambda environment variables
```
TZ - set envionment timezone
debug - if is set on True, lambda print important variables
```

Limitations of security scan
- If is used day of week mode, maximum duration is 7 days.
- In both modes security scan will fail if run hits the next month.

## Installation script 
Create lambda package or install requirements localy
```
 install.sh -i|--install -p|--package 
         -i|--install      install requirements
         -p|--package      create package for AWS lambda
         -h|--help         print this help menu 
```
