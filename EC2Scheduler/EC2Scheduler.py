import cronex
import boto3
import json
import time
import os
from datetime import datetime, timedelta
from botocore.exceptions import ClientError


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
tagList=["RUN:DAYS", "RUN:HOURS", "MANUAL", "OFFPEAK","NUM_INST", "SecureScanState"]
asgKeys=["AutoScalingGroupName", "Tags", "Instances", "DesiredCapacity", "MaxSize", "MinSize", "SuspendedProcesses"] 
ec2Keys=["InstanceId", "State", "Tags"]

def listsClear():
    """
    Clear list before run because Lambda caching global variables
    """
    startEC2List.clear()
    stopEC2List.clear()
    startAsgList.clear()
    stopAsgList.clear()
    asgScaleDown.clear()
    asgScaleUp.clear()

def getInstancetData(DataDict):
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
    Dict={}
    if DataDict["Tags"] != None:
        for key in asgKeys:
            Dict[key]=DataDict[key]
        for tag in DataDict["Tags"]:
            if tag["Key"] in tagList:
                Dict[tag["Key"]]=tag["Value"]
    return Dict

def getTagedInstances(ec2_client):
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
    try:
        List=[]
        responseDict = asg_client.describe_auto_scaling_groups()
        for asg in responseDict["AutoScalingGroups"]:
            List.append(getAsgData(asg))
        return List
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def getInstanceStatus(client, instanceId):
    try:
        responseDict = client.describe_instance_status(InstanceIds=[instanceId])
        return responseDict["InstanceStatuses"][0]["InstanceState"]["Name"]
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def getPreviousAsgSize(client, asgName):
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
    try:
        responseDict = client.describe_auto_scaling_groups(AutoScalingGroupNames=[asgName])
        return responseDict["AutoScalingGroups"][0]["DesiredCapacity"]
    except ClientError as e:
        print(e.response['Error']['Code'])
        pass

def addInstanceTag(client, instanceId, tagName, tagValue):
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
    try:
        if resource_dict["RUN:DAYS"].lower() == 'manual' or resource_dict["RUN:HOURS"].lower() == 'manual':
            return True
    except KeyError:
        try:
            print("Instance %s nema tagy pro scheduling" % resource_dict['InstanceId'])
            return "MissingTag"
        except KeyError:
            print("Asg %s nema tagy pro scheduling" % resource_dict['AutoScalingGroupName'])
    else:
        return False

def activeNow(resource_dict):
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
        print("Instance %s nema tagy pro scheduling" % resource_dict['InstanceId'])
        return False
    except (ValueError, IndexError):
        try:
            print("Spatne nastaveny cas u instance %s" % resource_dict['InstanceId'])
        except KeyError:
            print("Spatne nastaveny cas u asg %s" % resource_dict['AutoScalingGroupName'])
    else:
        return False
    
def activeToday(resource_dict):
    nowDay = datetime.today().strftime("%a").upper()
    try:
        if nowDay in resource_dict["RUN:DAYS"]:
            return True
    except KeyError:
        try:
            print("Instance %s nema tagy pro scheduling" % resource_dict['InstanceId'])
        except KeyError:
            print("Asg %s nema tagy pro scheduling" % resource_dict['AutoScalingGroupName'])
    else:
        return False

def offpeak(resource_dict):
    try:
        if int(resource_dict["OFFPEAK"]) == -1:
            return False
    except KeyError:
        try:
            print("ASG %s nema tag pro offpeak konfiguraci " % resource_dict['AutoScalingGroupName'])
        except KeyError:
            return False
    else:
        return True

def isSpecialDay(secureScanDay):
    pass

def timeForSS(secureScanDay, secureScanStartTime, secureScanDuration):
    """
    Check if is time for security scan - inputs scanDay, start hour and ruration in hours
    Append to list cron check_trigger result (True/False)
    Returning True if one of results is True
    """
    resultsList=[]
    curTime=time.localtime(time.time())[:5]
    hours=int(secureScanStartTime)+int(secureScanDuration)
    days=hours//24

    if "#" in secureScanDay:
        if int(secureScanDuration) == 1:
            resultsList.append(cronex.CronExpression("* "+secureScanStartTime+" * * "+secureScanDay).check_trigger(curTime))
        elif hours < 24:
            resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-"+str(int(secureScanStartTime)+int(secureScanDuration))+" * * "+secureScanDay).check_trigger(curTime))
        else:
            if hours == 24:
                if int(secureScanDay.split("#")[0])+1 > 6:
                    nextDay="0#"+int(secureScanDay.split("#")[1])+1
                else:
                    nextDay=secureScanDay.split("#")[0]+1+"#"+secureScanDay.split("#")[1]
                resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" * * "+secureScanDay).check_trigger(curTime))
                resultsList.append(cronex.CronExpression("* 0-1 * * "+nextDay).check_trigger(curTime))
            else:
                if days == 1:
                    if int(secureScanDay.split("#")[0])+1 > 6:
                        lastDay="0#"+str(int(secureScanDay.split("#")[1])+1)
                    else:
                        lastDay=str(int(secureScanDay.split("#")[0])+1)+"#"+secureScanDay.split("#")[1]
                    resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" * * "+secureScanDay).check_trigger(curTime))
                    resultsList.append(cronex.CronExpression("* 0"+str(hours-24)+" * * "+lastDay).check_trigger(curTime)) 
                else:
                    splitDayNumbers=secureScanDay.split("#")
                    if int(splitDayNumbers[0])+days <= 6:
                        nextDay=",".join(str(i) for i in range(int(splitDayNumbers[0])+1,int(splitDayNumbers[0])+days))+"#"+splitDayNumbers[1]
                        lastDay=str(int(splitDayNumbers[0])+days)+"#"+splitDayNumbers[1]
                        resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" * * "+secureScanDay).check_trigger(curTime))
                        resultsList.append(cronex.CronExpression("* 0-23 * * "+nextDay).check_trigger(curTime))
                        resultsList.append(cronex.CronExpression("* 0-"+str(hours-(24*days))+" * * "+lastDay).check_trigger(curTime))
                    else:
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
        if int(secureScanDuration) == 1:
            resultsList.append(cronex.CronExpression("* "+secureScanStartTime+" "+secureScanDay+" * *").check_trigger(curTime))
        elif hours < 24:
            resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-"+str(int(secureScanStartTime)+int(secureScanDuration))+" "+secureScanDay+" * *").check_trigger(curTime))
        else:
            if hours == 24:
                resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" "+secureScanDay+" * *").check_trigger(curTime))
                resultsList.append(cronex.CronExpression("* 0-1 "+str(int(secureScanDay)+1)+" * *").check_trigger(curTime))
            else:
                if days == 1:
                    resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" "+secureScanDay+" * *").check_trigger(curTime))
                    resultsList.append(cronex.CronExpression("* 0-"+str(hours-24)+" "+str(int(secureScanDay)+1)+" * *").check_trigger(curTime)) 
                else:
                    resultsList.append(cronex.CronExpression("* "+secureScanStartTime+"-23"+" "+secureScanDay+" * *").check_trigger(curTime))
                    resultsList.append(cronex.CronExpression("* 0-23 "+str(int(secureScanDay)+1)+"-"+str(int(secureScanDay)+days-1)+" * *").check_trigger(curTime))
                    resultsList.append(cronex.CronExpression("* 0-"+str(hours-(24*days))+" "+str(int(secureScanDay)+days)+" * *").check_trigger(curTime))

    if True in resultsList:
        return True
    else:
        return False

def securityScan(asg_list, instance_list):
    print("Zapinam vsechny instance")
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

def cleanupAfterSS(instance_list):
    print("Vypinam instance po security scanu")
    for instance in instance_list:
        try:
            if instance["SecureScanState"] == "stopped":
                stopEC2List.append(instance["InstanceId"])
                delInstanceTag(ec2_client, instance["InstanceId"], "SecureScanState")
        except KeyError:
            pass
        
def asgUpdates():
    if startAsgList:
        print("Zapinam HealthCheck u celkem %s ASG: %s" %(len(startAsgList), startAsgList))
        for asg in startAsgList:
            try:
                asg_client.resume_processes(AutoScalingGroupName=asg, ScalingProcesses=['HealthCheck'])
            except ClientError as e:
                print(e.response['Error']['Code'])
                pass

    if stopAsgList:
        print("Vypinam HealthCheck u celkem %s ASG: %s" %(len(stopAsgList), stopAsgList))
        for asg in stopAsgList:
            try:
                asg_client.suspend_processes(AutoScalingGroupName=asg, ScalingProcesses=['HealthCheck'])
            except ClientError as e:
                print(e.response['Error']['Code'])
                pass

    if asgScaleUp:
        print("Skaluju nahoru celkem %s ASG: %s" %(len(asgScaleUp), asgScaleUp))
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
        print("Skaluju dolu celkem %s ASG: %s" %(len(asgScaleDown), asgScaleDown))
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
    Operations with instances start/stop
    """
    if startEC2List:
        print("Startuji celkem %s instanci: %s" %(len(startEC2List), startEC2List))
        try:
            ec2_client.start_instances(InstanceIds=startEC2List)
        except ClientError as e:
                print(e.response['Error']['Code'])
                pass

    if stopEC2List:
        print("Vypinam celkem %s instanci: %s" %(len(stopEC2List), stopEC2List))
        try:
            ec2_client.stop_instances(InstanceIds=stopEC2List)
        except ClientError as e:
                print(e.response['Error']['Code'])
                pass

def main():
    if timeForSS(secureScanDay, secureScanStartTime, secureScanDuration) is True and int(secureScanDuration) > 0:
        securityScan(getAllAsgs(asg_client), getAllInstances(ec2_client))
    else:
        allInstances=getAllInstances(ec2_client)
        for inst in allInstances:
            if "SecureScanState" in inst:
                print("Spoustim cleanup po security scanu")
                cleanupAfterSS(allInstances)
        for asg in getTagedAsgs(asg_client):
            if isManual(asg):
                print("Tag manual u ASG %s je aktivni" % (asg["AutoScalingGroupName"]))
            else:
                print("Tag manual u ASG %s je neaktivni" % (asg["AutoScalingGroupName"]))
                try:
                    asg["NUM_INST"]
                except KeyError:           
                    asg["NUM_INST"]=0
                activeNowV=activeNow(asg)
                activeTodayV=activeToday(asg)
                offpeakV=offpeak(asg)
                if (activeNowV is True 
                        and activeTodayV is True 
                        and next((True for item in asg["SuspendedProcesses"] if item["ProcessName"] == "HealthCheck"),False) is True 
                        and offpeakV is False):
                    startAsgList.append(asg["AutoScalingGroupName"])
                elif (
                        (activeNowV is False or activeTodayV is False) 
                        and asg["SuspendedProcesses"] == [] 
                        and offpeakV is False):
                    stopAsgList.append(asg["AutoScalingGroupName"])
                elif (offpeakV is True 
                        and activeNowV is True 
                        and activeTodayV is True 
                        and asg["SuspendedProcesses"] == [] 
                        and (asg["MinSize"] == 0 
                            or int(asg["NUM_INST"]) > asg["MinSize"] 
                            or asg["MinSize"] < int(asg["OFFPEAK"]))):
                    asgScaleUp.append(asg["AutoScalingGroupName"])
                elif (offpeakV is True 
                        and (activeNowV is False or activeTodayV is False) 
                        and asg["SuspendedProcesses"] == [] 
                        and asg["MinSize"] > int(asg["OFFPEAK"])):
                    asgScaleDown.append(asg["AutoScalingGroupName"])
        for instance in getTagedInstances(ec2_client):
            if isManual(instance):
                print("Tag manual u Instance %s je aktivni" % (instance["InstanceId"]))
            else:
                print("Tag manual u Instance %s je neaktivni" % (instance["InstanceId"]))
                activeNowV=activeNow(instance)
                activeTodayV=activeToday(instance)
                offpeakV=offpeak(instance)
                if activeNowV is True and activeTodayV is True and instance["State"]["Name"] == "stopped" and offpeakV is False:
                    startEC2List.append(instance["InstanceId"])
                elif (activeNowV is False or activeTodayV is False) and instance["State"]["Name"] == "running" and offpeakV is False:
                    stopEC2List.append(instance["InstanceId"]) 

def debug():
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
    print("Running EC2 Scheduler %s" % datetime.today())
    listsClear()
    main()
    asgUpdates()
    instanceUpdates()
