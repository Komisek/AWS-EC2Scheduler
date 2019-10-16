import cronex
import boto3
import json
import time
import os
from datetime import datetime, timedelta
from botocore.exceptions import ClientError

# Version
version = "16102019"

# Declare clients
region="eu-central-1"
ec2_client = boto3.client("ec2", region_name=region)
asg_client = boto3.client("autoscaling", region_name=region)

# Declare Vars
startEC2List = []
stopEC2List = []
startAsgList = []
stopAsgList = []
asgScaleDown = []
asgScaleUp = []
secureScanDay = str(os.environ["secureScanDay"])
secureScanStartTime = str(os.environ["secureScanStartTime"])
secureScanDuration = str(os.environ["secureScanDuration"])
debugEnv = str(os.environ["debug"])
tagList=["RUN:DAYS", "RUN:HOURS", "MANUAL", "OFFPEAK","NUM_INST", "SecureScanState"]
asgKeys=["AutoScalingGroupName", "Tags", "Instances", "DesiredCapacity", "MaxSize", "MinSize", "SuspendedProcesses"] 
ec2Keys=["InstanceId", "State", "Tags"]

def listsClear():
    """
    Clear list before run because AWS Lambda caching global variables
    """
    startEC2List.clear()
    stopEC2List.clear()
    startAsgList.clear()
    stopAsgList.clear()
    asgScaleDown.clear()
    asgScaleUp.clear()

def getTagedInstances(ec2_client):
    """
    Return instances with tags in tagList
    
    @param ec2 boto3 client
    @return AWS response as dict
    """
    try:
        List=[]
        responseDict = ec2_client.describe_instances(
            Filters=[{
                'Name': 'instance-state-name',
                'Values': ['stopped', 'running']
                },
                {'Name': 'tag-key', 'Values': tagList
                }]
        )
        for instances in responseDict["Reservations"]:
            List.append(getInstancetData(instances["Instances"]))
        return List
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def getAllInstances(ec2_client):
    """
    Return all instances in account

    @param ec2 boto3 client
    @return AWS response as dict
    """
    try:
        List=[]
        responseDict = ec2_client.describe_instances(
            Filters=[{
                'Name': 'instance-state-name',
                'Values': ['stopped', 'running']
                }]
        )
        for instances in responseDict["Reservations"]:
            List.append(getInstancetData(instances["Instances"]))
        return List
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def getTagedAsgs(asg_client):
    """
    Return autoscaling groups with tags in tagList

    @param asg boto3 client
    @return AWS response as dict
    """
    try:
        List=[]
        responseDict = asg_client.describe_auto_scaling_groups()
        for asg in responseDict["AutoScalingGroups"]:
            if next((True for item in asg["Tags"] if item["Key"] in tagList),False):
                List.append(getAsgData(asg))
        return List
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def getAllAsgs(asg_client):
    """
    Return all autoscaling groups in account

    @param asg boto3 client
    @return AWS response as dict
    """
    try:
        List=[]
        responseDict = asg_client.describe_auto_scaling_groups()
        for asg in responseDict["AutoScalingGroups"]:
            List.append(getAsgData(asg))
        return List
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def getInstancetData(DataDict):
    """
    Return instances details

    @param DataDict - instances list as a dict
    @return AWS response as dict
    """
    Dict={}
    for instance in DataDict:
        if instance["Tags"] != None:
            for key in ec2Keys:
                Dict[key]=instance[key]
            for tag in instance["Tags"]:
                if tag["Key"] in tagList:
                    Dict[tag["Key"]]=tag["Value"]
    return Dict

def getAsgData(DataDict):
    """
    Return autoscaling group details

    @param autoscaling groups list as a dict
    @return AWS response as dict
    """
    Dict={}
    if DataDict["Tags"] != None:
        for key in asgKeys:
            Dict[key]=DataDict[key]
        for tag in DataDict["Tags"]:
            if tag["Key"] in tagList:
                Dict[tag["Key"]]=tag["Value"]
    return Dict

def getInstanceStatus(client, instanceId):
    """
    Return instance state of instance. (running,stopped,...)

    @param client - ec2 boto3 client
    @param instanceID - AWS instanceID
    @return instance state string
    """
    try:
        responseDict = client.describe_instance_status(InstanceIds=[instanceId])
        return responseDict["InstanceStatuses"][0]["InstanceState"]["Name"]
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def getPreviousAsgSize(client, asgName):
    """
    Return previous instances value. After security scan or scale down.

    @param client - asg boto3 client
    @param asgName - AWS autoscaling group name
    @return value from asg tag
    """
    try:
        responseDict = client.describe_tags(
            Filters=[{
                'Name': 'auto-scaling-group', 
                'Values': [asgName]
                }]
            )
        return next((item for item in responseDict["Tags"] if item["Key"] == "NUM_INST"),None)
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def getCurrentAsgSize(client, asgName):
    """
    Return number of running instances in autoscaling group.
    
    @param client - asg boto3 client
    @param asgName - AWS autoscaling group name
    @return value from asg tag
    """
    try:
        responseDict = client.describe_auto_scaling_groups(AutoScalingGroupNames=[asgName])
        return responseDict["AutoScalingGroups"][0]["DesiredCapacity"]
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def addInstanceTag(client, instanceId, tagName, tagValue):
    """
    Add instance tag.

    @param client - ec2 boto3 client
    @param instanceId - AWS instanceID
    @param tagName - string
    @param tagValue - string 
    """
    try:
        client.create_tags(
            Resources=[
                instanceId,
            ],
            Tags=[{
                'Key': tagName,
                'Value': tagValue
            }]
        )
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def delInstanceTag(client, instanceId, tagName):
    """
    Delete instance tag.

    @param client - ec2 boto3 client
    @param instanceId - AWS instanceID
    @param tagName - string
    """
    try:
        client.delete_tags(
            Resources=[
                instanceId,
            ],
            Tags=[{
                'Key': tagName
            }]
        )
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def addAsgTag(client, asgName, tagName, tagValue):
    """
    Add tag to autoscaling group.

    @param client - asg boto3 client
    @param asgName - AWS autoscaling group name
    @param tagName - string
    @param tagValue - string 
    """
    try:
        client.create_or_update_tags(
            Tags=[{
                "ResourceId": asgName,
                "ResourceType": "auto-scaling-group",
                "Key": tagName,
                "Value": str(tagValue),
                "PropagateAtLaunch": True
            }]
        )
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def delAsgTag(client, asgName, tagName):
    """
    Delete tag from autoscaling group.

    @param client - asg boto3 client
    @param asgName - AWS autoscaling group name
    @param tagName - string
    """
    try:
        client.delete_tags(
            Tags=[{
                "ResourceId": asgName,
                "ResourceType": "auto-scaling-group",
                "Key": tagName
            }]
        )
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def getOffpeakValue(client, asgName):
    """
    Return value offpeak configuration from asg

    @param client - asg boto3 client
    @param asgName - AWS autoscaling group name
    @return value from asg tag
    """
    try:
        responseDict = client.describe_tags(
            Filters=[{
                'Name': 'auto-scaling-group', 
                'Values': [asgName]
                }]
            )
        return next((item for item in responseDict["Tags"] if item["Key"] == "OFFPEAK"),None)
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def isManual(resource_dict):
    """
    Check if manual tag is enabled

    @param dict
    @return boolean or MissingTag
    """
    try:
        if resource_dict["RUN:DAYS"].lower() == 'manual' or resource_dict["RUN:HOURS"].lower() == 'manual':
            return True
    except KeyError:
        try:
            print("Instance %s haven't tags for scheduling" % resource_dict['InstanceId'])
            return "MissingTag"
        except KeyError:
            print("Asg %s haven't tags for scheduling" % resource_dict['AutoScalingGroupName'])
    else:
        return False

def activeNow(resource_dict):
    """
    Check RUN:HOURS tag if instance can run now.

    time record examples:
    01:00-20:00 (run from 1AM to 8PM)
    06:00-17:00 (run from 6AM to 5PM)
    06:00-01:00 (run from 6AM to 1AM next day)

    @param dict
    @return boolean
    """
    try:
        nowTimestamp = int(datetime.now().strftime("%H"))*60+int(datetime.now().strftime("%M"))
        hoursActive = resource_dict["RUN:HOURS"].split("-")
        startTimestamp=int(hoursActive[0].split(":")[0])*60+int(hoursActive[0].split(":")[1])
        stopTimestamp=int(hoursActive[1].split(":")[0])*60+int(hoursActive[1].split(":")[1])
        if stopTimestamp < startTimestamp:
            if nowTimestamp in range(0, stopTimestamp) or nowTimestamp in range(startTimestamp, 23*60+59):
                return True
        if nowTimestamp in range(startTimestamp, stopTimestamp):
            return True
    except KeyError:
        print("Instance %s haven't tags for scheduling" % resource_dict['InstanceId'])
        return False
    except (ValueError, IndexError):
        try:
            print("Wrong time set in instance %s" % resource_dict['InstanceId'])
        except KeyError:
            print("Wrong time set in asg %s" % resource_dict['AutoScalingGroupName'])
    else:
        return False
    
def activeToday(resource_dict):
    """
    Check RUN:DAYS tag if instance or asg can run today

    List of instance working days 
    [MON,TUE,WED,THU,FRI,SAT,SUN]

    @param dict
    @return boolean
    """
    nowDay = datetime.today().strftime("%a").upper()
    try:
        if nowDay in resource_dict["RUN:DAYS"]:
            return True
    except KeyError:
        try:
            print("Instance %s haven't tags for scheduling" % resource_dict['InstanceId'])
        except KeyError:
            print("Asg %s haven't tags for scheduling" % resource_dict['AutoScalingGroupName'])
    else:
        return False

def offpeak(resource_dict):
    """
    Check offpeak configuration for autoscaling group.

    Number of instances running out of working hours.

    OFFPEAK = -1 - Affects ASG group with disabling HealtCheck. With this settings u can stop instance in ASG without terminating.

    @param dict
    @return boolean
    """
    try:
        if int(resource_dict["OFFPEAK"]) == -1:
            return False
    except KeyError:
        try:
            print("ASG %s haven't tags for offpeak configuration " % resource_dict['AutoScalingGroupName'])
        except KeyError:
            return False
    else:
        return True

def timeForSS(secureScanDay, secureScanStartTime, secureScanDuration):
    """
    Check if is time for security scan - inputs scanDay, start hour and ruration in hours
    Append to list cron check_trigger result (True/False)
    Returning True if one of results is True

    @param secureScanDay - str (num day 1-31 or day in week 0#1-6#5)
    @param secureScanDuration - str
    @param secureScanStartTime - str
    @return boolean


    """
    resultsList=[]
    curTime=time.localtime(time.time())[:5]
    hours=int(secureScanStartTime)+int(secureScanDuration)
    days=hours//24
    
    # Check special run day record (0#1 etc.)
    if "#" in secureScanDay:
        # Check duration of SS
        if int(secureScanDuration) == 1:
            resultsList.append(cronex.CronExpression("* "+secureScanStartTime+" * * "+secureScanDay).check_trigger(curTime))
        elif hours < 24:
            resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-"+str(int(secureScanStartTime)+int(secureScanDuration))+" * * "+secureScanDay).check_trigger(curTime))
        else:
            # Duration is 24 hours
            if hours == 24:
                # Check if duration going to next week
                if int(secureScanDay.split("#")[0])+1 > 6:
                    nextDay="0#"+int(secureScanDay.split("#")[1])+1
                else:
                    nextDay=secureScanDay.split("#")[0]+1+"#"+secureScanDay.split("#")[1]
                resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" * * "+secureScanDay).check_trigger(curTime))
                resultsList.append(cronex.CronExpression("* 0-1 * * "+nextDay).check_trigger(curTime))
            else:
                # Duration is 24 to 47 hours
                if days == 1:
                    # Check if duration going to next week
                    if int(secureScanDay.split("#")[0])+1 > 6:
                        lastDay="0#"+str(int(secureScanDay.split("#")[1])+1)
                    else:
                        lastDay=str(int(secureScanDay.split("#")[0])+1)+"#"+secureScanDay.split("#")[1]
                    resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" * * "+secureScanDay).check_trigger(curTime))
                    resultsList.append(cronex.CronExpression("* 0"+str(hours-24)+" * * "+lastDay).check_trigger(curTime)) 
                else:
                    # Duration is 48 hours and more
                    splitDayNumbers=secureScanDay.split("#")
                    # SS fit in single week
                    if int(splitDayNumbers[0])+days <= 6:
                        nextDay=",".join(str(i) for i in range(int(splitDayNumbers[0])+1,int(splitDayNumbers[0])+days))+"#"+splitDayNumbers[1]
                        lastDay=str(int(splitDayNumbers[0])+days)+"#"+splitDayNumbers[1]
                        resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" * * "+secureScanDay).check_trigger(curTime))
                        resultsList.append(cronex.CronExpression("* 0-23 * * "+nextDay).check_trigger(curTime))
                        resultsList.append(cronex.CronExpression("* 0-"+str(hours-(24*days))+" * * "+lastDay).check_trigger(curTime))
                    else:
                        # SS duration goint to next week
                        if ((int(splitDayNumbers[0])+days+1)//7) == 1:
                            if int(splitDayNumbers[0])+1 == 7:
                                nextWeek=",".join(str(i) for i in range(0,(int(splitDayNumbers[0])+days)-7))+"#"+str(int(splitDayNumbers[1])+1)
                            else:
                                nextDay=",".join(str(i) for i in range(int(splitDayNumbers[0])+1,7))+"#"+splitDayNumbers[1]
                                nextWeek=",".join(str(i) for i in range(0,(int(splitDayNumbers[0])+days)-7))+"#"+str(int(splitDayNumbers[1])+1)
                                resultsList.append(cronex.CronExpression("* 0-23 * * "+nextDay).check_trigger(curTime))
                            lastDay=str(int(splitDayNumbers[0])+days-7)+"#"+str(int(splitDayNumbers[1])+1)
                            resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" * * "+secureScanDay).check_trigger(curTime))
                            resultsList.append(cronex.CronExpression("* 0-23 * * "+nextWeek).check_trigger(curTime))
                            resultsList.append(cronex.CronExpression("* 0-"+str(hours-(24*days))+" * * "+lastDay).check_trigger(curTime))
                        else:
                            print("Longer run than week is not implemented")
    else:
        # Check duration of SS
        if int(secureScanDuration) == 1:
            resultsList.append(cronex.CronExpression("* "+secureScanStartTime+" "+secureScanDay+" * *").check_trigger(curTime))
        elif hours < 24:
            resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-"+str(int(secureScanStartTime)+int(secureScanDuration))+" "+secureScanDay+" * *").check_trigger(curTime))
        else:
            # Duration is 24 hours
            if hours == 24:
                resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" "+secureScanDay+" * *").check_trigger(curTime))
                resultsList.append(cronex.CronExpression("* 0-1 "+str(int(secureScanDay)+1)+" * *").check_trigger(curTime))
            else:
                # Duration is 24 to 47 hours
                if days == 1:
                    resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" "+secureScanDay+" * *").check_trigger(curTime))
                    resultsList.append(cronex.CronExpression("* 0-"+str(hours-24)+" "+str(int(secureScanDay)+1)+" * *").check_trigger(curTime)) 
                else:
                    # Duration is 48 hours and more
                    resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" "+secureScanDay+" * *").check_trigger(curTime))
                    resultsList.append(cronex.CronExpression("* 0-23 "+str(int(secureScanDay)+1)+"-"+str(int(secureScanDay)+days-1)+" * *").check_trigger(curTime))
                    resultsList.append(cronex.CronExpression("* 0-"+str(hours-(24*days))+" "+str(int(secureScanDay)+days)+" * *").check_trigger(curTime))

    if True in resultsList:
        return True
    else:
        return False

def securityScan(asg_list, instance_list):
    """
    Run security scan. Scale up all autoscaling groups. Start all stopped instances. 

    @param asg_list - list
    @param instance_list - list

    """
    print("Security Scan Enabled - Starting all instances")
    for asg in asg_list:
        if asg["MinSize"] == 0:
            asgScaleUp.append(asg["AutoScalingGroupName"])
            print((asg["AutoScalingGroupName"],asg["MinSize"]))

    for instance in instance_list:
        if instance["State"]["Name"] == "stopped":
            manual=isManual(instance)
            if manual:
                addInstanceTag(ec2_client, instance["InstanceId"], "SecureScanState", "stopped")
            elif manual == "MissingTag":
                addInstanceTag(ec2_client, instance["InstanceId"], "SecureScanState", "stopped")
            startEC2List.append(instance["InstanceId"])
            print((instance["InstanceId"], instance["State"]["Name"]))

def cleanupAfterSS(instanceId):
    """
    Delete security scan tag from instances, after security scan is ended.

    @param instanceId - AWS instance id
    """
    print("Stop instance %s after security scan" % (instanceId))
    stopEC2List.append(instanceId)
    delInstanceTag(ec2_client, instanceId, "SecureScanState")
        
def asgUpdates():
    """
    Operations with autoscaling groups 
    - enable or disable healthcheck
    - scale up or down
    """
    if startAsgList:
        print("Enable HealthCheck for %s ASGs: %s" %(len(startAsgList), startAsgList))
        for asg in startAsgList:
            try:
                asg_client.resume_processes(AutoScalingGroupName=asg, ScalingProcesses=['HealthCheck'])
            except ClientError as e:
                print(e.response['Error']['Code'])
                pass

    if stopAsgList:
        print("Disable HealthCheck for %s ASGs: %s" %(len(stopAsgList), stopAsgList))
        for asg in stopAsgList:
            try:
                asg_client.suspend_processes(AutoScalingGroupName=asg, ScalingProcesses=['HealthCheck'])
            except ClientError as e:
                print(e.response['Error']['Code'])
                pass

    if asgScaleUp:
        print("Scale up %s ASGs: %s" %(len(asgScaleUp), asgScaleUp))
        for asg in asgScaleUp:
            if timeForSS(secureScanDay, secureScanStartTime, secureScanDuration) is False:
                numInst=getPreviousAsgSize(asg_client, asg)["Value"]
                delAsgTag(asg_client,asg,"NUM_INST")
            else:
                numInst=1
            try:
                asg_client.update_auto_scaling_group(
                    AutoScalingGroupName=asg,
                    MinSize=int(numInst),
                    DesiredCapacity=int(numInst))
            except ClientError as e:
                print(e.response['Error']['Code'])
                pass

    if asgScaleDown:
        print("Scale down %s ASGs: %s" %(len(asgScaleDown), asgScaleDown))
        for asg in asgScaleDown:
            numInst=getCurrentAsgSize(asg_client, asg)
            addAsgTag(asg_client, asg, "NUM_INST", numInst)
            if int(getOffpeakValue(asg_client, asg)["Value"]) > 0:
                runInst=getOffpeakValue(asg_client, asg)["Value"]
            else:
                runInst=0
            try:
                asg_client.update_auto_scaling_group(
                    AutoScalingGroupName=asg,
                    MinSize=int(runInst),
                    DesiredCapacity=int(runInst))
            except ClientError as e:
                print(e.response['Error']['Code'])
                pass

def instanceUpdates():
    """
    Operations with instances - start/stop
    """
    if startEC2List:
        print("Starting %s instances: %s" %(len(startEC2List), startEC2List))
        try:
            ec2_client.start_instances(InstanceIds=startEC2List)
        except ClientError as e:
                print(e.response['Error']['Code'])
                pass

    if stopEC2List:
        print("Stopping %s instances: %s" %(len(stopEC2List), stopEC2List))
        try:
            ec2_client.stop_instances(InstanceIds=stopEC2List)
        except ClientError as e:
                print(e.response['Error']['Code'])
                pass

def main():
    """
    Main function 
    """
    # Check if is time for SecurityScan
    if timeForSS(secureScanDay, secureScanStartTime, secureScanDuration) is True and int(secureScanDuration) > 0:
        securityScan(getAllAsgs(asg_client), getAllInstances(ec2_client))
    else:
        allInstances=getAllInstances(ec2_client)
        # Cleanup after security scan run only if AWS response include "SecureScanState" tag
        for inst in allInstances:
            if "SecureScanState" in inst:
                cleanupAfterSS(inst["InstanceId"])
        # Check autoscaling groups state and tags
        for asg in getTagedAsgs(asg_client):
            # check if tag manual is included
            if isManual(asg):
                print("ASG %s - manual config: enabled" % (asg["AutoScalingGroupName"]))
            else:
                print("ASG %s - manual config: disabled" % (asg["AutoScalingGroupName"]))
                # Get previous number of instances in autoscaling group. When tag is not defined set to 0
                try:
                    asg["NUM_INST"]
                except KeyError:           
                    asg["NUM_INST"]=0
                activeNowV=activeNow(asg)
                activeTodayV=activeToday(asg)
                offpeakV=offpeak(asg)
                # Autoscalingroup state is (HealthCheck - suspended, running time true, ofpeeak = -1) -> enable healthcheck
                if (activeNowV is True 
                        and activeTodayV is True 
                        and next((True for item in asg["SuspendedProcesses"] if item["ProcessName"] == "HealthCheck"),False) is True 
                        and offpeakV is False):
                    startAsgList.append(asg["AutoScalingGroupName"])
                # Autoscalingroup state is (HealthCheck - not suspended, running time false, , ofpeeak = -1) -> disable healthcheck
                elif (
                        (activeNowV is False or activeTodayV is False) 
                        and asg["SuspendedProcesses"] == [] 
                        and offpeakV is False):
                    stopAsgList.append(asg["AutoScalingGroupName"])
                # Autoscalingroup state is (running time true, ofpeeak >= 0, Min size is 0 or less than NUM_INST) -> scale up
                elif (offpeakV is True 
                        and activeNowV is True 
                        and activeTodayV is True 
                        and asg["SuspendedProcesses"] == [] 
                        and (asg["MinSize"] == 0 
                            or int(asg["NUM_INST"]) > asg["MinSize"] 
                            or asg["MinSize"] < int(asg["OFFPEAK"]))):
                    asgScaleUp.append(asg["AutoScalingGroupName"])
                # Autoscalingroup state is (running time false, ofpeeak >= 0, Min size is more than OFFPEAK) -> scale down
                elif (offpeakV is True 
                        and (activeNowV is False or activeTodayV is False) 
                        and asg["SuspendedProcesses"] == [] 
                        and asg["MinSize"] > int(asg["OFFPEAK"])):
                    asgScaleDown.append(asg["AutoScalingGroupName"])

        # Check instances state and tags
        for instance in getTagedInstances(ec2_client):
            # check if tag manual is included
            if isManual(instance):
                print("Instance %s - manual config: enabled" % (instance["InstanceId"]))
            else:
                print("Instance %s - manual config: disabled" % (instance["InstanceId"]))
                activeNowV=activeNow(instance)
                activeTodayV=activeToday(instance)
                offpeakV=offpeak(instance)
                # Instance state is (running time true, state stopped) -> start instance
                if activeNowV is True and activeTodayV is True and instance["State"]["Name"] == "stopped" and offpeakV is False:
                    startEC2List.append(instance["InstanceId"])
                # Instance state is (running time false, state running) -> stop instance
                elif (activeNowV is False or activeTodayV is False) and instance["State"]["Name"] == "running" and offpeakV is False:
                    stopEC2List.append(instance["InstanceId"]) 

def debug():
    """
    Print important run variables
    """
    print("startEC2List - %s" % (startEC2List))
    print("stopEC2List - %s" % (stopEC2List))
    print("startAsgList - %s" % (startAsgList))
    print("stopAsgList - %s" % (stopAsgList))
    print("asgScaleUp - %s" % (asgScaleUp))
    print("asgScaleDown - %s" % (asgScaleDown))

    print("timeForSS - %s" % (timeForSS(secureScanDay, secureScanStartTime, secureScanDuration)))
    print("secureScanDay - %s" % (secureScanDay))
    print("secureScanStartTime - %s" % (secureScanStartTime))
    print("secureScanDuration - %s" % (secureScanDuration))

def lambda_handler(event, context):
    """
    Call AWS lambda function
    """
    print("Running EC2 Scheduler %s - version %s" % (datetime.today(), version))
    listsClear()
    main()
    asgUpdates()
    instanceUpdates()

    if debugEnv == "True":
        debug()

