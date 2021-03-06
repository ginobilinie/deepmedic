# Copyright (c) 2016, Konstantinos Kamnitsas
# All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the BSD license. See the accompanying LICENSE file
# or read the terms at https://opensource.org/licenses/BSD-3-Clause.

import numpy
import numpy as np

import theano
import theano.tensor as T
from theano.tensor.nnet import conv
import random
from math import floor
from math import ceil

from deepmedic.cnnLayerTypes import ConvLayerWithSoftmax
from deepmedic.cnnLayerTypes import ConvLayer


#-----helper functions that I use in here---
def getListOfNumberOfCentralVoxelsClassifiedPerDimension(imagePartDimensions, patchDimensions) :
    numberOfCentralVoxelsClassifiedPerDimension = []
    for dimension_i in xrange(0, len(imagePartDimensions)) :
	numberOfCentralVoxelsClassifiedPerDimension.append(imagePartDimensions[dimension_i] - patchDimensions[dimension_i] + 1)
    return numberOfCentralVoxelsClassifiedPerDimension


##################################
## Various activation functions ##
##################################
#### rectified linear unit
def ReLU(x):
    y = T.maximum(0.0, x)
    return(y)
#### sigmoid
def Sigmoid(x):
    y = T.nnet.sigmoid(x)
    return(y)
#### tanh
def Tanh(x):
    y = T.tanh(x)
    return(y)


##################################################
##################################################
################ THE CNN CLASS ###################
##################################################
##################################################

class Cnn3d(object):
    def __init__(self):

	self.cnnModelName = None

	self.costFunctionLetter = "" # "L", "D" or "J"

        self.cnnLayers = []
        self.cnnLayersSubsampled = []
        self.fcLayers = []
	self.cnnLayersZoomed1 = []
	self.CNN_PATHWAY_NORMAL = 0; self.CNN_PATHWAY_SUBSAMPLED = 1; self.CNN_PATHWAY_FC = 2; self.CNN_PATHWAY_ZOOMED1 = 3;
        self.typesOfCnnLayers = [self.cnnLayers,
				self.cnnLayersSubsampled,
				self.fcLayers,
				self.cnnLayersZoomed1
				];

	self.classificationLayer = ""

	self.numberOfOutputClasses = None

        self.initialLearningRate = "" #used by exponential schedule
        self.learning_rate = theano.shared(np.cast["float32"](0.01)) #initial value, changed in make_cnn_model().compileTrainingFunction()
        self.L1 = ""  # the factor in the cost function. Sum of absolutes of all weights
        self.L1_reg_constant = "" #l1 regularization constant. Given.
        self.L2_sqr = "" # the factor in the cost function. Sum of sqr of all weights
        self.L2_reg_constant = "" #l2 regularization constant. Given.

        self.cnnTrainModel = ""
        self.cnnValidateModel = ""
        self.cnnTestModel = ""
        self.cnnVisualiseFmFunction = ""

	#=======FOR OPTIMIZERs================
	self.sgd0orAdam1orRmsProp2 = None
	self.classicMomentum0OrNesterov1 = None
	#SGD + Classic momentum: (to save the momentum)
        self.initialMomentum = "" #used by exponential schedule
        self.momentum = theano.shared(np.cast["float32"](0.))
        self.momentumTypeNONNormalized0orNormalized1 = None
	self.velocities_forMom = [] #list of shared_variables. Each of the individual Dws is a sharedVar. This whole thing isnt.
        #ADAM:
	self.b1_adam = None
	self.b2_adam = None
	self.epsilonForAdam = None
	self.i_adam = theano.shared(np.cast["float32"](0.)) #Current iteration of adam
	self.m_listForAllParamsAdam = [] #list of mean of grads for all parameters, for ADAM optimizer.
	self.v_listForAllParamsAdam = [] #list of variances of grads for all parameters, for ADAM optimizer.
	#RMSProp
	self.rho_rmsProp = None
	self.epsilonForRmsProp = None
	self.accuGradSquare_listForAllParamsRmsProp = [] #the rolling average accumulator of the variance of the grad (grad^2)

	#=====================================
        self.sharedTrainingNiiData_x = ""
        self.sharedValidationNiiData_x = ""
        self.sharedTestingNiiData_x = ""
        self.sharedTrainingNiiLabels_y = ""
        self.sharedValidationNiiLabels_y = ""
        self.sharedTrainingCoordinates_of_patches_for_epoch = ""
        self.sharedValidationCoordinates_of_patches_for_epoch = ""
        self.sharedTestingCoordinates_of_patches_for_epoch = ""
        
        self.borrowFlag = ""
        self.imagePartDimensionsTraining = ""
        self.imagePartDimensionsValidation = ""
        self.imagePartDimensionsTesting = ""
        self.subsampledImagePartDimensionsTraining = ""
        self.subsampledImagePartDimensionsValidation = ""
        self.subsampledImagePartDimensionsTesting = ""

        self.batchSize = ""
        self.batchSizeValidation = ""
        self.batchSizeTesting = ""
        self.number_of_images_in_shared = ""
        #self.patchesToTrainPerImagePart = ""
        self.dataTypeX = ""
        self.nkerns = "" #number of feature maps.
	self.nkernsSubsampled = ""
	self.subsampleFactor = ""
        self.patchDimensions = ""
	#Fully Connected Layers
	self.kernelDimensionsFirstFcLayer = ""

        self.numberOfCentralVoxelsClassifiedPerDimension = ""
        self.numberOfCentralVoxelsClassifiedPerDimensionTesting = ""   

	self.softmaxTemperature = 1

	#Batch normalization (rolling average)
	self.usingBatchNormalization = False
	self.indexWhereRollingAverageIs = 0 #Index in the rolling-average matrices of the layers, of the entry to update in the next batch.
	self.rollingAverageForBatchNormalizationOverThatManyBatches = ""

	self.numberOfEpochsTrained = 0

	#Automatically lower CNN's learning rate by looking at validation accuracy:
	self.topMeanValidationAccuracyAchievedInEpoch = [-1,-1]
	self.lastEpochAtTheEndOfWhichLrWasLowered = 0 #refers to CnnTrained epochs, not the epochs in the do_training loop.
	


    def change_learning_rate_of_a_cnn(self, newValueForLearningRate, myLogger=None) :
	stringToPrint = "UPDATE: (epoch-cnn-trained#" + str(self.numberOfEpochsTrained) +") Changing the Cnn's Learning Rate to: "+str(newValueForLearningRate)
	if myLogger<>None :
        	myLogger.print3( stringToPrint )
	else :
		print stringToPrint
        self.learning_rate.set_value(newValueForLearningRate)
	self.lastEpochAtTheEndOfWhichLrWasLowered = self.numberOfEpochsTrained

    def divide_learning_rate_of_a_cnn_by(self, divideLrBy, myLogger=None) :
	oldLR = self.learning_rate.get_value()
        newValueForLearningRate = oldLR*1.0/divideLrBy
	self.change_learning_rate_of_a_cnn(newValueForLearningRate, myLogger)

	
    def change_momentum_of_a_cnn(self, newValueForMomentum, myLogger=None):
	stringToPrint = "UPDATE: (epoch-cnn-trained#" + str(self.numberOfEpochsTrained) +") Changing the Cnn's Momentum to: "+str(newValueForMomentum)
	if myLogger<>None :
        	myLogger.print3( stringToPrint )
	else :
		print stringToPrint
        self.momentum.set_value(newValueForMomentum)

    def multiply_momentum_of_a_cnn_by(self, multiplyMomentumBy, myLogger=None) :
	oldMom = self.momentum.get_value()
        newValueForMomentum = oldMom*multiplyMomentumBy
	self.change_momentum_of_a_cnn(newValueForMomentum, myLogger)

    def changeB1AndB2ParametersOfAdam(self, b1ParamForAdam, b2ParamForAdam, myLogger) :
	myLogger.print3("UPDATE: (epoch-cnn-trained#" + str(self.numberOfEpochsTrained) +") Changing the Cnn's B1 and B2 parameters for ADAM optimization to: B1="+str(b1ParamForAdam) + " || B2=" + str(b2ParamForAdam))
	self.b1_adam = b1ParamForAdam
	self.b2_adam = b2ParamForAdam

    def changeRhoParameterOfRmsProp(self, rhoParamForRmsProp, myLogger) :
	myLogger.print3("UPDATE: (epoch-cnn-trained#" + str(self.numberOfEpochsTrained) +") Changing the Cnn's Rho parameter for RMSProp optimization to: Rho="+str(rhoParamForRmsProp))
	self.rho_rmsProp = rhoParamForRmsProp


    def checkMeanValidationAccOfLastEpochAndUpdateCnnsTopAccAchievedIfNeeded(self,
									myLogger,
									meanValidationAccuracyOfLastEpoch,
									minIncreaseInValidationAccuracyConsideredForLrSchedule) :
	#Called at the end of an epoch, right before increasing self.numberOfEpochsTrained
	highestAchievedValidationAccuracyOfCnn = self.topMeanValidationAccuracyAchievedInEpoch[0]
	if meanValidationAccuracyOfLastEpoch > highestAchievedValidationAccuracyOfCnn + minIncreaseInValidationAccuracyConsideredForLrSchedule :
		self.topMeanValidationAccuracyAchievedInEpoch[0] = meanValidationAccuracyOfLastEpoch
		self.topMeanValidationAccuracyAchievedInEpoch[1] = self.numberOfEpochsTrained
		myLogger.print3("UPDATE: In this last epoch (cnnTrained) #" + str(self.topMeanValidationAccuracyAchievedInEpoch[1]) + " the CNN achieved a new highest mean validation accuracy of :" + str(self.topMeanValidationAccuracyAchievedInEpoch[0]) )


    def freeGpuTrainingData(self) :
	self.sharedTrainingNiiData_x.set_value(np.zeros([1,1,1,1,1], dtype="float32"))# = []
	self.sharedTrainingSubsampledData_x.set_value(np.zeros([1,1,1,1,1], dtype="float32"))
	self.sharedTrainingNiiLabels_y.set_value(np.zeros([1,1,1,1], dtype="float32"))# = []

    def freeGpuValidationData(self) :
	self.sharedValidationNiiData_x.set_value(np.zeros([1,1,1,1,1], dtype="float32"))# = []
	self.sharedValidationSubsampledData_x.set_value(np.zeros([1,1,1,1,1], dtype="float32"))
	self.sharedValidationNiiLabels_y.set_value(np.zeros([1,1,1,1], dtype="float32"))# = []

    def freeGpuTestingData(self) :
	self.sharedTestingNiiData_x.set_value(np.zeros([1,1,1,1,1], dtype="float32"))# = []
	self.sharedTestingSubsampledData_x.set_value(np.zeros([1,1,1,1,1], dtype="float32"))


    #for inference with batch-normalization. Every training batch, this is called to update an internal matrix of each layer, with the last mus and vars, so that I can compute the rolling average for inference.
    def updateTheMatricesOfTheLayersWithTheLastMusAndVarsForTheRollingAverageOfTheBatchNormInference(self) :

	if not self.usingBatchNormalization : #Not using batch normalization. Nothing to do here.
		return

	for layer_type_i in xrange(0, len(self.typesOfCnnLayers)) :
		for layer_i in xrange(0, len(self.typesOfCnnLayers[layer_type_i])) :
			if not (layer_type_i == self.CNN_PATHWAY_FC and layer_i == len(self.typesOfCnnLayers[self.CNN_PATHWAY_FC])-1 ) :
				thisIterationLayer = self.typesOfCnnLayers[layer_type_i][layer_i]
				layerMuArrayValue = thisIterationLayer.muBnsArrayForRollingAverage.get_value()
				layerMuArrayValue[self.indexWhereRollingAverageIs] = thisIterationLayer.sharedNewMu_B.get_value()
				thisIterationLayer.muBnsArrayForRollingAverage.set_value(layerMuArrayValue, borrow=True)

				layerVarArrayValue = thisIterationLayer.varBnsArrayForRollingAverage.get_value()
				layerVarArrayValue[self.indexWhereRollingAverageIs] = thisIterationLayer.sharedNewVar_B.get_value()
				thisIterationLayer.varBnsArrayForRollingAverage.set_value(layerVarArrayValue, borrow=True)
	self.indexWhereRollingAverageIs = (self.indexWhereRollingAverageIs + 1) % self.rollingAverageForBatchNormalizationOverThatManyBatches


    def makeLayersOfThisPathwayAndReturnDimensionsOfOutputFM(self,
							thisPathwayType,
							thisPathWayNKerns,
							thisPathWayKernelDimensions,
							inputImageToPathway,
							inputImageToPathwayInference,
							inputImageToPathwayTesting,
							numberOfImageChannelsToPathway,
							imagePartDimensionsTraining,
							imagePartDimensionsValidation,
							imagePartDimensionsTesting,
							rollingAverageForBatchNormalizationOverThatManyBatches,
							maxPoolingParamsStructureForThisPathwayType,
							initializationTechniqueClassic0orDelvingInto1,
							activationFunctionToUseRelu0orPrelu1,
							thisPathwayDropoutRates=[]
							) :

	rng = numpy.random.RandomState(55789)

	shapeOfInputImageToPathway = [self.batchSize, numberOfImageChannelsToPathway] + imagePartDimensionsTraining
	shapeOfInputImageToPathwayValidation = [self.batchSizeValidation, numberOfImageChannelsToPathway] + imagePartDimensionsValidation
	shapeOfInputImageToPathwayTesting = [self.batchSizeTesting, numberOfImageChannelsToPathway] + imagePartDimensionsTesting

	previousLayerOutputImage = inputImageToPathway
	previousLayerOutputImageInference = inputImageToPathwayInference
	previousLayerOutputImageTesting = inputImageToPathwayTesting
	previousLayerOutputImageShape = shapeOfInputImageToPathway
	previousLayerOutputImageShapeValidation = shapeOfInputImageToPathwayValidation
	previousLayerOutputImageShapeTesting = shapeOfInputImageToPathwayTesting

	for layer_i in xrange(0, len(thisPathWayNKerns)) :
		thisLayerFilterShape = [thisPathWayNKerns[layer_i],
					previousLayerOutputImageShape[1], #number of feature maps of last layer.
					thisPathWayKernelDimensions[layer_i][0],
					thisPathWayKernelDimensions[layer_i][1],
					thisPathWayKernelDimensions[layer_i][2]]

		thisLayerDropoutRate = thisPathwayDropoutRates[layer_i] if thisPathwayDropoutRates else 0

		thisLayerMaxPoolingParameters = maxPoolingParamsStructureForThisPathwayType[layer_i]

		layer_instance = ConvLayer(rng,
						    input=previousLayerOutputImage, #WOWOWOWWOWOWOW Check this out! Passing in the class a 'non initialized' matrix! But reshaped to correct dimensions!
						    inputInferenceBn=previousLayerOutputImageInference,
						    inputTestingBn=previousLayerOutputImageTesting,
						    image_shape=previousLayerOutputImageShape,
						    image_shapeValidation=previousLayerOutputImageShapeValidation,
						    image_shapeTesting=previousLayerOutputImageShapeTesting,
						    filter_shape=thisLayerFilterShape,
						    poolsize=(0, 0),
						    #for batchNormalization
						    rollingAverageForBatchNormalizationOverThatManyBatches=rollingAverageForBatchNormalizationOverThatManyBatches,
						    maxPoolingParameters=thisLayerMaxPoolingParameters,
						    initializationTechniqueClassic0orDelvingInto1=initializationTechniqueClassic0orDelvingInto1,
						    activationFunctionToUseRelu0orPrelu1=activationFunctionToUseRelu0orPrelu1,
						    dropoutRate=thisLayerDropoutRate
						) 
		self.typesOfCnnLayers[thisPathwayType].append(layer_instance)

		previousLayerOutputImage = layer_instance.output
		previousLayerOutputImageInference = layer_instance.outputInference
		previousLayerOutputImageTesting = layer_instance.outputTesting
		previousLayerOutputImageShape = layer_instance.outputImageShape
		previousLayerOutputImageShapeValidation = layer_instance.outputImageShapeValidation
		previousLayerOutputImageShapeTesting = layer_instance.outputImageShapeTesting


	return [previousLayerOutputImageShape, previousLayerOutputImageShapeValidation, previousLayerOutputImageShapeTesting]


    def repeatRczTheOutputOfLayerBySubsampleFactorToMatchDimensionsOfOtherFm(self,
									   layerOutputToRepeat,
									   dimensionsOfFmToMatch ) :
	# dimensionsOfFmToMatch should be [batch_size, numberOfFms, r, c , z]. I care for RCZ.
	#Now I need to repeat the output in the three dimensions, so that it has 9x9x9 dimensions.
	expandedOutputR = layerOutputToRepeat.repeat(self.subsampleFactor[0],axis = 2)
	expandedOutputRC = expandedOutputR.repeat(self.subsampleFactor[1],axis = 3)
	expandedOutputRCZ = expandedOutputRC.repeat(self.subsampleFactor[2],axis = 4)
	expandedOutput = expandedOutputRCZ
	#If the central-voxels are eg 10, the susampled-part will have 4 central voxels. Which above will be repeated to 3*4 = 12. I need to clip the last ones, to have the same dimension as the input from 1st pathway, which will have dimensions equal to the centrally predicted voxels (10)
	expandedOutput = expandedOutput[:,
					:,
					:dimensionsOfFmToMatch[2],
					:dimensionsOfFmToMatch[3],
					:dimensionsOfFmToMatch[4]]
	return expandedOutput


    def getMiddlePartOfFms(self, fms, fmsShape, listOfNumberOfCentralVoxelsToGetPerDimension) :
	#if part is of even width, one voxel to the left is the centre.
	rCentreOfPartIndex = (fmsShape[2] - 1) / 2
	rIndexToStartGettingCentralVoxels = rCentreOfPartIndex - (listOfNumberOfCentralVoxelsToGetPerDimension[0]-1)/2
	rIndexToStopGettingCentralVoxels = rIndexToStartGettingCentralVoxels + listOfNumberOfCentralVoxelsToGetPerDimension[0] #Excluding
	cCentreOfPartIndex = (fmsShape[3] - 1) / 2
	cIndexToStartGettingCentralVoxels = cCentreOfPartIndex - (listOfNumberOfCentralVoxelsToGetPerDimension[1]-1)/2
	cIndexToStopGettingCentralVoxels = cIndexToStartGettingCentralVoxels + listOfNumberOfCentralVoxelsToGetPerDimension[1] #Excluding

	if len(listOfNumberOfCentralVoxelsToGetPerDimension) == 2: #the input FMs are of 2 dimensions (for future use)
		return fms[:,:,
			rIndexToStartGettingCentralVoxels : rIndexToStopGettingCentralVoxels,
			cIndexToStartGettingCentralVoxels : cIndexToStopGettingCentralVoxels]
	elif len(listOfNumberOfCentralVoxelsToGetPerDimension) ==3 :  #the input FMs are of 3 dimensions
		zCentreOfPartIndex = (fmsShape[4] - 1) / 2
		zIndexToStartGettingCentralVoxels = zCentreOfPartIndex - (listOfNumberOfCentralVoxelsToGetPerDimension[2]-1)/2
		zIndexToStopGettingCentralVoxels = zIndexToStartGettingCentralVoxels + listOfNumberOfCentralVoxelsToGetPerDimension[2] #Excluding
		return fms[:, :,
			rIndexToStartGettingCentralVoxels : rIndexToStopGettingCentralVoxels,
			cIndexToStartGettingCentralVoxels : cIndexToStopGettingCentralVoxels,
			zIndexToStartGettingCentralVoxels : zIndexToStopGettingCentralVoxels]
	else : #wrong number of dimensions!
		return -1



    def makeMultiscaleConnectionsForLayerType(self,
					typeOfLayers_index,
					convLayersToConnectToFirstFcForMultiscaleFromThisLayerType,
					numberOfFmsOfInputToFirstFcLayer,
					inputToFirstFcLayer,
					inputToFirstFcLayerInference,
					inputToFirstFcLayerTesting) :

	layersInThisPathway = self.typesOfCnnLayers[typeOfLayers_index]

	if typeOfLayers_index <> self.CNN_PATHWAY_SUBSAMPLED :
		numberOfCentralVoxelsToGet = self.numberOfCentralVoxelsClassifiedPerDimension
		numberOfCentralVoxelsToGetValidation = self.numberOfCentralVoxelsClassifiedPerDimensionValidation
		numberOfCentralVoxelsToGetTesting = self.numberOfCentralVoxelsClassifiedPerDimensionTesting

	else : #subsampled pathway... You get one more voxel if they do not get divited by subsampleFactor exactly.
		numberOfCentralVoxelsToGet = [ int(ceil(self.numberOfCentralVoxelsClassifiedPerDimension[0]*1.0/self.subsampleFactor[0])),
						int(ceil(self.numberOfCentralVoxelsClassifiedPerDimension[1]*1.0/self.subsampleFactor[1])),
						int(ceil(self.numberOfCentralVoxelsClassifiedPerDimension[2]*1.0/self.subsampleFactor[2]))]
		numberOfCentralVoxelsToGetValidation = [ int(ceil(self.numberOfCentralVoxelsClassifiedPerDimensionValidation[0]*1.0/self.subsampleFactor[0])),
						int(ceil(self.numberOfCentralVoxelsClassifiedPerDimensionValidation[1]*1.0/self.subsampleFactor[1])),
						int(ceil(self.numberOfCentralVoxelsClassifiedPerDimensionValidation[2]*1.0/self.subsampleFactor[2]))]
		numberOfCentralVoxelsToGetTesting = [ int(ceil(self.numberOfCentralVoxelsClassifiedPerDimensionTesting[0]*1.0/self.subsampleFactor[0])),
						int(ceil(self.numberOfCentralVoxelsClassifiedPerDimensionTesting[1]*1.0/self.subsampleFactor[1])),
						int(ceil(self.numberOfCentralVoxelsClassifiedPerDimensionTesting[2]*1.0/self.subsampleFactor[2]))
						]

	for convLayer_i in convLayersToConnectToFirstFcForMultiscaleFromThisLayerType :
		thisLayer = layersInThisPathway[convLayer_i]
		outputOfLayer = thisLayer.output
		outputOfLayerInference = thisLayer.outputInference
		outputOfLayerTesting = thisLayer.outputTesting
			
		middlePartOfFms = self.getMiddlePartOfFms(outputOfLayer, thisLayer.outputImageShape, numberOfCentralVoxelsToGet)
		middlePartOfFmsInference = self.getMiddlePartOfFms(outputOfLayerInference, thisLayer.outputImageShapeValidation, numberOfCentralVoxelsToGetValidation)
		middlePartOfFmsTesting = self.getMiddlePartOfFms(outputOfLayerTesting, thisLayer.outputImageShapeTesting, numberOfCentralVoxelsToGetTesting)


		if typeOfLayers_index == self.CNN_PATHWAY_SUBSAMPLED :
			shapeOfOutputOfLastLayerOf1stPathway = self.typesOfCnnLayers[self.CNN_PATHWAY_NORMAL][-1].outputImageShape
			shapeOfOutputOfLastLayerOf1stPathwayValidation = self.typesOfCnnLayers[self.CNN_PATHWAY_NORMAL][-1].outputImageShapeValidation
			shapeOfOutputOfLastLayerOf1stPathwayTesting = self.typesOfCnnLayers[self.CNN_PATHWAY_NORMAL][-1].outputImageShapeTesting
			middlePartOfFms = self.repeatRczTheOutputOfLayerBySubsampleFactorToMatchDimensionsOfOtherFm(
													middlePartOfFms,
													shapeOfOutputOfLastLayerOf1stPathway )
			middlePartOfFmsInference = self.repeatRczTheOutputOfLayerBySubsampleFactorToMatchDimensionsOfOtherFm(
													middlePartOfFmsInference,
													shapeOfOutputOfLastLayerOf1stPathwayValidation )
			middlePartOfFmsTesting = self.repeatRczTheOutputOfLayerBySubsampleFactorToMatchDimensionsOfOtherFm(
													middlePartOfFmsTesting,
													shapeOfOutputOfLastLayerOf1stPathwayTesting )

		numberOfFmsOfInputToFirstFcLayer = numberOfFmsOfInputToFirstFcLayer + thisLayer.outputImageShape[1]
		inputToFirstFcLayer = T.concatenate([inputToFirstFcLayer, middlePartOfFms], axis=1)
		inputToFirstFcLayerInference = T.concatenate([inputToFirstFcLayerInference, middlePartOfFmsInference], axis=1)
		inputToFirstFcLayerTesting = T.concatenate([inputToFirstFcLayerTesting, middlePartOfFmsTesting], axis=1)

	return [numberOfFmsOfInputToFirstFcLayer, inputToFirstFcLayer, inputToFirstFcLayerInference, inputToFirstFcLayerTesting]



    #========================================OPTIMIZERS========================================
    """
	From https://github.com/lisa-lab/pylearn2/pull/136#issuecomment-10381617 :
	ClassicMomentum:
	(1) v_t = mu * v_t-1 - lr * gradient_f(params_t)
	(2) params_t = params_t-1 + v_t
	(3) params_t = params_t-1 + mu * v_t-1 - lr * gradient_f(params_t-1)

	Nesterov momentum:
	(4) v_t = mu * v_t-1 - lr * gradient_f(params_t-1 + mu * v_t-1)
	(5) params_t = params_t-1 + v_t

	alternate formulation for Nesterov momentum:
	(6) v_t = mu * v_t-1 - lr * gradient_f(params_t-1)
	(7) params_t = params_t-1 + mu * v_t - lr * gradient_f(params_t-1)
	(8) params_t = params_t-1 + mu**2 * v_t-1 - (1+mu) * lr * gradient_f(params_t-1)

	Can also find help for optimizers in Lasagne: https://github.com/Lasagne/Lasagne/blob/master/lasagne/updates.py
    """


    def getUpdatesAccordingToSgd(self,
					cost,
					paramsToOptDuringTraining
					) :
        # create a list of gradients for all model parameters
        grads = T.grad(cost, paramsToOptDuringTraining)
        
        #========================= Momentum ===========================
        
	self.velocities_forMom = []
        updates = []

	#The below will be 1 if nonNormalized momentum, and (1-momentum) if I am using normalized momentum.
	multiplierForCurrentGradUpdateForNonNormalizedOrNormalizedMomentum = 1.0 - self.momentum*self.momentumTypeNONNormalized0orNormalized1

        for param, grad  in zip(paramsToOptDuringTraining, grads) :

            v = theano.shared(param.get_value()*0., broadcastable=param.broadcastable)
            self.velocities_forMom.append(v)

            stepToGradientDirection = multiplierForCurrentGradUpdateForNonNormalizedOrNormalizedMomentum*self.learning_rate*grad
            newVelocity = self.momentum*v - stepToGradientDirection

            if self.classicMomentum0OrNesterov1 == 0 :
            	updateToParam = newVelocity
            else : #Nesterov
            	updateToParam = self.momentum*newVelocity - stepToGradientDirection

            updates.append((v, newVelocity)) #I can do (1-mom)*learnRate*grad.
            updates.append((param, param + updateToParam))

	return updates

    def getUpdatesAccordingToRmsProp(self,
				cost,
				params,
				epsilon=1e-6
				) :

	#epsilon=1e-4 #I got NaN in cost function when I ran it with epsilon=1e-6. So lets try if this was the problem...

	#Code taken and updated (it was V2 of paper, updated to V8) from https://gist.github.com/Newmu/acb738767acb4788bac3
        grads = T.grad(cost, params)
        updates = []
        self.accuGradSquare_listForAllParamsRmsProp = []
	self.velocities_forMom = []

	#The below will be 1 if nonNormalized momentum, and (1-momentum) if I am using normalized momentum.
	multiplierForCurrentGradUpdateForNonNormalizedOrNormalizedMomentum = 1.0 - self.momentum*self.momentumTypeNONNormalized0orNormalized1

        for param, grad in zip(params, grads):
            accu = theano.shared(param.get_value()*0., broadcastable=param.broadcastable) #accumulates the mean of the grad's square.
            self.accuGradSquare_listForAllParamsRmsProp.append(accu)

            v = theano.shared(param.get_value()*0., broadcastable=param.broadcastable) #velocity
            self.velocities_forMom.append(v)

            accu_new = self.rho_rmsProp * accu + (1 - self.rho_rmsProp) * T.sqr(grad)

            stepToGradientDirection = multiplierForCurrentGradUpdateForNonNormalizedOrNormalizedMomentum*(self.learning_rate * grad /T.sqrt(accu_new + epsilon))

            newVelocity = self.momentum*v - stepToGradientDirection

            if self.classicMomentum0OrNesterov1 == 0 :
            	updateToParam = newVelocity
            else : #Nesterov
            	updateToParam = self.momentum*newVelocity - stepToGradientDirection

            updates.append((accu, accu_new))
            updates.append((v, newVelocity)) #I can do (1-mom)*learnRate*grad.
            updates.append((param, param + updateToParam))

        return updates


    def getUpdatesAccordingToAdam(self,
				cost,
				params,
				epsilon = 10**(-8) #According to paper.
				) :
	#Code is on par with version V8 of Kingma's paper.
        grads = T.grad(cost, params)

        updates = []

	self.i_adam = theano.shared(np.cast["float32"](0.)) #Current iteration
	self.m_listForAllParamsAdam = [] #list of mean of grads for all parameters, for ADAM optimizer.
	self.v_listForAllParamsAdam = [] #list of variances of grads for all parameters, for ADAM optimizer.

	i = self.i_adam
        i_t = i + 1.
        fix1 = 1. - (self.b1_adam)**i_t
        fix2 = 1. - (self.b2_adam)**i_t
        lr_t = self.learning_rate * (T.sqrt(fix2) / fix1)
        for param, grad in zip(params, grads):
            m = theano.shared(param.get_value() * 0.)
            self.m_listForAllParamsAdam.append(m)
            v = theano.shared(param.get_value() * 0.)
            self.v_listForAllParamsAdam.append(v)
            m_t = (self.b1_adam * m) + ((1. - self.b1_adam) * grad)
            v_t = (self.b2_adam * v) + ((1. - self.b2_adam) * T.sqr(grad)) #Double check this with the paper.
            grad_t = m_t / (T.sqrt(v_t) + epsilon)
            param_t = param - (lr_t * grad_t)
            updates.append((m, m_t))
            updates.append((v, v_t))
            updates.append((param, param_t))
        updates.append((i, i_t))
        return updates


    #NOTE: compileNewTrainFunction() changes the self.initialLearningRate. Which is used for the exponential schedule!
    def compileNewTrainFunction(self, myLogger, layersOfLayerTypesToTrain, learning_rate,
				sgd0orAdam1orRmsProp2,
					classicMomentum0OrNesterov1,
					momentum,
					momentumTypeNONNormalized0orNormalized1,
					b1ParamForAdam,
					b2ParamForAdam,
					epsilonForAdam,
					rhoParamForRmsProp,
					epsilonForRmsProp,
				costFunctionLetter = "previous") :
	myLogger.print3("...Building the function for training...")
	
	#symbolic variables needed:
	index = T.lscalar()
	x = self.symbolicXForUseToReCompileTrainFunction
	xSubsampled = self.symbolicXSubsampledForUseToReCompileTrainFunction
	#y = T.ivector('y')  # the labels are presented as 1D vector of [int] labels
	yUnflat = T.itensor4()
	y=yUnflat.flatten(1) # the labels are presented as 1D vector of [int] labels
        intCastSharedTrainingNiiLabels_y = T.cast( self.sharedTrainingNiiLabels_y, 'int32')
	inputVectorWeightsOfClassesInCostFunction = T.fvector() #These two were added to counter class imbalance by changing the weights in the cost function
	weightsOfClassesInCostFunction = T.fvector() #...in the first few epochs, until I get to an ok local minimum area.
	#THE ABOVE ARE GIVEN A VALUE IN THE 'GIVENS' PARAMETER OF THE COMPILED FUNCTION! WHICH IS FURTHER BELOW IN THIS FUNCTION-BLOCK!
        #BEAR IN MIND THAT ALTHOUGH IN THE TUTORIAL IT SAYS THAT 'GIVENS' IS TO REPLACE THE VALUE OF A SHARED VARIABLE, IT IS FOR 'ANY' VARIABLE
        #E.G. FOR THESE TWO TOO, WHICH ARE NOT SHARED!

	myLogger.print3("DEBUG: compileNewTrainFunction() changes the self.initialLearningRate. It's now set to:" + str(learning_rate))
	self.initialLearningRate = learning_rate
	self.change_learning_rate_of_a_cnn(learning_rate, myLogger)

        # =======create a list of all model PARAMETERS (weights and biases) to be fit by gradient descent=======
	# ======= And REGULARIZATION

	paramsToOptDuringTraining = None #Ws and Bs
	self.L1 = None
	self.L2_sqr = None
	for type_of_layer_i in xrange(0, len(self.typesOfCnnLayers) ) :
		for layer_i in xrange(0, len(self.typesOfCnnLayers[type_of_layer_i]) ) :
			if layersOfLayerTypesToTrain == "all" or (layer_i in layersOfLayerTypesToTrain[type_of_layer_i]) :
				paramsToOptDuringTraining = self.typesOfCnnLayers[type_of_layer_i][layer_i].params if paramsToOptDuringTraining == None else paramsToOptDuringTraining + self.typesOfCnnLayers[type_of_layer_i][layer_i].params

			self.L1 = abs(self.typesOfCnnLayers[type_of_layer_i][layer_i].W).sum() if self.L1 == None else self.L1 + abs(self.typesOfCnnLayers[type_of_layer_i][layer_i].W).sum()
        		self.L2_sqr = (self.typesOfCnnLayers[type_of_layer_i][layer_i].W ** 2).sum() if self.L2_sqr == None else self.L2_sqr + (self.typesOfCnnLayers[type_of_layer_i][layer_i].W ** 2).sum()

        #==========================COST FUNCTION=======================
        # the cost we minimize during training is the NLL of the model
	if costFunctionLetter <> "previous" :
		self.costFunctionLetter = costFunctionLetter

	#The cost Function to use.
	myLogger.print3("DEBUG: The training function of the CNN is going to use cost-function:" + str(self.costFunctionLetter))
	if self.costFunctionLetter == "L" :
		costFunctionFromLastLayer = self.fcLayers[-1].negativeLogLikelihood(y, weightsOfClassesInCostFunction)
	else :
		myLogger.print3("ERROR: Problem in make_cnn_model(). The parameter self.costFunctionLetter did not have an acceptable value( L,D,J ). Exiting.")
		exit(1)
	
        cost = (costFunctionFromLastLayer
                + self.L1_reg_constant * self.L1
                + self.L2_reg_constant * self.L2_sqr
                )
      

	#============================OPTIMIZATION=============================
	self.sgd0orAdam1orRmsProp2 = sgd0orAdam1orRmsProp2
	self.classicMomentum0OrNesterov1 = classicMomentum0OrNesterov1
	myLogger.print3("DEBUG: compileNewTrainFunction() changes the self.initialMomentum. It's now set to:" + str(momentum))
	self.initialMomentum = momentum
	self.momentumTypeNONNormalized0orNormalized1 = momentumTypeNONNormalized0orNormalized1
	self.change_momentum_of_a_cnn(momentum, myLogger)

	updates = None
	if sgd0orAdam1orRmsProp2 == 0 :
		myLogger.print3("UPDATE: The optimizer that will be used is SGD! Momentum used: Classic0 or Nesterov1 =" + str(classicMomentum0OrNesterov1))
		updates = self.getUpdatesAccordingToSgd(cost,
							paramsToOptDuringTraining
							)
	elif sgd0orAdam1orRmsProp2 == 1 :
		myLogger.print3("UPDATE: The optimizer that will be used is ADAM! No momentum implemented for Adam!")
		self.changeB1AndB2ParametersOfAdam(b1ParamForAdam, b2ParamForAdam, myLogger)
		self.epsilonForAdam = epsilonForAdam
		updates = self.getUpdatesAccordingToAdam(cost,
						paramsToOptDuringTraining,
						epsilonForAdam
						)
	elif sgd0orAdam1orRmsProp2 == 2 :
		myLogger.print3("UPDATE: The optimizer that will be used is RMSProp! Momentum used: Classic0 or Nesterov1 =" + str(classicMomentum0OrNesterov1))
		self.changeRhoParameterOfRmsProp(rhoParamForRmsProp, myLogger)
		self.epsilonForRmsProp = epsilonForRmsProp
		updates = self.getUpdatesAccordingToRmsProp(cost,
						paramsToOptDuringTraining,
						epsilonForRmsProp
						)
	
	#================BATCH NORMALIZATION UPDATES======================
	if self.usingBatchNormalization :
		#These are not the variables of the normalization of the FMs' distributions that are optimized during training. These are only the Mu and Stds that are used during inference,
		#... and here we update the sharedVariable which is used "from the outside during do_training()" to update the rolling-average-matrix for inference. Do for all layers.
		for layer_type_i in xrange( 0, len(self.typesOfCnnLayers) ) :
		    for layer_i in xrange( 0, len(self.typesOfCnnLayers[layer_type_i]) ) :
			if not ( (layer_type_i == self.CNN_PATHWAY_FC) and (layer_i == len(self.typesOfCnnLayers[self.CNN_PATHWAY_FC])-1) ) : #if it is not the very last FC-classification layer... 
			    theCertainLayer = self.typesOfCnnLayers[layer_type_i][layer_i]
			    updates.append((theCertainLayer.sharedNewMu_B, theCertainLayer.newMu_B)) #CAREFUL: WARN, PROBLEM, THEANO BUG! If a layer has only 1FM, the .newMu_B ends up being of type (true,) instead of vector!!! Error!!!
			    updates.append((theCertainLayer.sharedNewVar_B, theCertainLayer.newVar_B))
	
        #========================COMPILATION OF FUNCTIONS =================
        classificationLayer = self.typesOfCnnLayers[self.CNN_PATHWAY_FC][-1]

	if not self.usingSubsampledPathway : # This is to avoid warning from theano for unused input (xSubsampled), in case I am not using the pathway.
		givensSet = { x: self.sharedTrainingNiiData_x[index * self.batchSize: (index + 1) * self.batchSize],
				yUnflat: intCastSharedTrainingNiiLabels_y[index * self.batchSize: (index + 1) * self.batchSize],
				weightsOfClassesInCostFunction: inputVectorWeightsOfClassesInCostFunction }
	else :
		givensSet = { x: self.sharedTrainingNiiData_x[index * self.batchSize: (index + 1) * self.batchSize],
                		xSubsampled: self.sharedTrainingSubsampledData_x[index * self.batchSize: (index + 1) * self.batchSize],
				yUnflat: intCastSharedTrainingNiiLabels_y[index * self.batchSize: (index + 1) * self.batchSize],
				weightsOfClassesInCostFunction: inputVectorWeightsOfClassesInCostFunction }

	myLogger.print3("...Compiling the function for training... (This may take a few minutes...)")
        self.cnnTrainModel = theano.function(
				[index, inputVectorWeightsOfClassesInCostFunction],
				[cost, classificationLayer.meanErrorTraining(y)] + classificationLayer.multiclassRealPosAndNegAndTruePredPosNegTraining0OrValidation1(y,0),
				updates=updates,
				givens = givensSet
				)

	myLogger.print3("The function for training was compiled.")

    def compileNewValidationFunction(self, myLogger) :
	myLogger.print3("...Building the function for validation...")
	
	#symbolic variables needed:
	index = T.lscalar()
	x = self.symbolicXForUseToReCompileTrainFunction
	xSubsampled = self.symbolicXSubsampledForUseToReCompileTrainFunction
	y = T.ivector('y')  # the labels are presented as 1D vector of [int] labels
	yUnflat = T.itensor4()
	y = yUnflat.flatten(1)
        intCastSharedValidationNiiLabels_y = T.cast( self.sharedValidationNiiLabels_y, 'int32')

        classificationLayer = self.typesOfCnnLayers[self.CNN_PATHWAY_FC][-1]

	if not self.usingSubsampledPathway : # This is to avoid warning from theano for unused input (xSubsampled), in case I am not using the pathway.
		givensSet = { x: self.sharedValidationNiiData_x[index * self.batchSizeValidation: (index + 1) * self.batchSizeValidation],
                		yUnflat: intCastSharedValidationNiiLabels_y[index * self.batchSizeValidation: (index + 1) * self.batchSizeValidation] }
	else :
		givensSet = { x: self.sharedValidationNiiData_x[index * self.batchSizeValidation: (index + 1) * self.batchSizeValidation],
                		xSubsampled: self.sharedValidationSubsampledData_x[index * self.batchSizeValidation: (index + 1) * self.batchSizeValidation],
                		yUnflat: intCastSharedValidationNiiLabels_y[index * self.batchSizeValidation: (index + 1) * self.batchSizeValidation] }

	myLogger.print3("...Compiling the function for validation... (This may take a few minutes...)")
        self.cnnValidateModel = theano.function(
				[index],
				[classificationLayer.meanErrorValidation(y)] + classificationLayer.multiclassRealPosAndNegAndTruePredPosNegTraining0OrValidation1(y,1),
				givens = givensSet
				)
   	myLogger.print3("The function for validation was compiled.")


    def compileNewTestFunction(self, myLogger) :
	myLogger.print3("...Building the function for testing...")
	
	#symbolic variables needed:
	index = T.lscalar()
	x = self.symbolicXForUseToReCompileTrainFunction
	xSubsampled = self.symbolicXSubsampledForUseToReCompileTrainFunction

        # create a function to compute the mistakes that are made by the model
        classificationLayer = self.typesOfCnnLayers[self.CNN_PATHWAY_FC][-1]

	if not self.usingSubsampledPathway : # This is to avoid warning from theano for unused input (xSubsampled), in case I am not using the pathway.
		givensSet = { x: self.sharedTestingNiiData_x[index * self.batchSizeTesting: (index + 1) * self.batchSizeTesting] }
	else :
		givensSet = { x: self.sharedTestingNiiData_x[index * self.batchSizeTesting: (index + 1) * self.batchSizeTesting],
                		xSubsampled: self.sharedTestingSubsampledData_x[index * self.batchSizeTesting: (index + 1) * self.batchSizeTesting] }

	myLogger.print3("...Compiling the function for testing... (This may take a few minutes...)")
        self.cnnTestModel = theano.function(
				[index],
				classificationLayer.predictionProbabilities(),
				givens = givensSet
				)
	myLogger.print3("The function for testing was compiled.")



	
    def compileNewVisualisationFunctionForWhole(self, myLogger) :
	myLogger.print3("...Building the function for visualisation of FMs...")
	
	#symbolic variables needed:
	index = T.lscalar()
	x = self.symbolicXForUseToReCompileTrainFunction
	xSubsampled = self.symbolicXSubsampledForUseToReCompileTrainFunction

	listToReturnWithAllTheFmActivationsAppended = []
        for type_of_layer_i in xrange(0,len(self.typesOfCnnLayers)) : #0=simple pathway, 1 = subsampled pathway, 2 = fc layers, 3 = zoomedIn1.
            for layer_i in xrange(0, len(self.typesOfCnnLayers[type_of_layer_i])) : #each layer that this pathway/fc has.
		listToReturnWithAllTheFmActivationsAppended.append(self.typesOfCnnLayers[type_of_layer_i][layer_i].fmsActivations([0,9999]))

	if not self.usingSubsampledPathway : # This is to avoid warning from theano for unused input (xSubsampled), in case I am not using the pathway.
		givensSet = { x: self.sharedTestingNiiData_x[index * self.batchSizeTesting: (index + 1) * self.batchSizeTesting] }
	else :
		givensSet = { x: self.sharedTestingNiiData_x[index * self.batchSizeTesting: (index + 1) * self.batchSizeTesting],
				xSubsampled: self.sharedTestingSubsampledData_x[index * self.batchSizeTesting: (index + 1) * self.batchSizeTesting] }

	myLogger.print3("...Compiling the function for visualisation of FMs... (This may take a few minutes...)")
	self.cnnVisualiseAllFmsFunction = theano.function(
                                        [index],
                                        listToReturnWithAllTheFmActivationsAppended,
                                        givens = givensSet
                                    )
	myLogger.print3("The function for visualisation of FMs was compiled.")

    def compileNewTestAndVisualisationFunctionForWhole(self, myLogger) :
	myLogger.print3("...Building the function for testing and visualisation of FMs...")
	
	#symbolic variables needed:
	index = T.lscalar()
	x = self.symbolicXForUseToReCompileTrainFunction
	xSubsampled = self.symbolicXSubsampledForUseToReCompileTrainFunction

	listToReturnWithAllTheFmActivationsAndPredictionsAppended = []
        for type_of_layer_i in xrange(0,len(self.typesOfCnnLayers)) : #0=simple pathway, 1 = subsampled pathway, 2 = fc layers, 3 = zoomedIn1.
            for layer_i in xrange(0, len(self.typesOfCnnLayers[type_of_layer_i])) : #each layer that this pathway/fc has.
		listToReturnWithAllTheFmActivationsAndPredictionsAppended.append(self.typesOfCnnLayers[type_of_layer_i][layer_i].fmsActivations([0,9999]))

        classificationLayer = self.typesOfCnnLayers[self.CNN_PATHWAY_FC][-1]
        listToReturnWithAllTheFmActivationsAndPredictionsAppended.append(classificationLayer.predictionProbabilitiesReshaped1())
	if not self.usingSubsampledPathway : # This is to avoid warning from theano for unused input (xSubsampled), in case I am not using the pathway.
		givensSet = { x: self.sharedTestingNiiData_x[index * self.batchSizeTesting: (index + 1) * self.batchSizeTesting] }
	else :
		givensSet = { x: self.sharedTestingNiiData_x[index * self.batchSizeTesting: (index + 1) * self.batchSizeTesting],
				xSubsampled: self.sharedTestingSubsampledData_x[index * self.batchSizeTesting: (index + 1) * self.batchSizeTesting] }

	myLogger.print3("...Compiling the function for testing and visualisation of FMs... (This may take a few minutes...)")
	self.cnnTestAndVisualiseAllFmsFunction = theano.function(
				                        [index],
				                        listToReturnWithAllTheFmActivationsAndPredictionsAppended,
				                        givens = givensSet
				                    	)
	myLogger.print3("The function for testing and visualisation of FMs was compiled.")


    def make_cnn_model(self,
                       myLogger,
                       cnnModelName,
                       costFunctionLetter,

                       imagePartDimensionsTraining ,
                       patchDimensions,

                       numberOfImageChannelsPath1,
                       numberOfImageChannelsPath2,

                       nkerns,
                       kernelDimensions,
                       batch_size,
                       batch_size_validation,
                       batch_size_testing,
                       #===OPTIMIZATION====
                       learning_rate,
                       sgd0orAdam1orRmsProp2,
                       classicMomentum0OrNesterov1,
                       momentum,
                       momentumTypeNONNormalized0orNormalized1,
                       b1ParamForAdam,
                       b2ParamForAdam,
                       epsilonForAdam,
                       rhoParamForRmsProp,
                       epsilonForRmsProp,
                       #===COST FUNCTION====
                       L1_reg_constant,
                       L2_reg_constant,
                       softmaxTemperature,
                       borrowFlag,
                       #-----for the extendedVersion---
                       subsampledImagePartDimensionsTraining,
                       nkernsSubsampled,
                       kernelDimensionsSubsampled,
                       subsampleFactor,

                       #-----Fully Connected Layers---
                       fcLayersFMs,
                       kernelDimensionsFirstFcLayer,

                       #----for the zoomed-in pathway----
                       zoomedInPatchDimensions,
                       nkernsZoomedIn1,
                       kernelDimensionsZoomedIn1,

                       #---MAX POOLING---
                       maxPoolingParamsStructure,

                       #for BatchNormalization
                       rollingAverageForBatchNormalizationOverThatManyBatches,

                       imagePartDimensionsValidation,
                       subsampledImagePartDimensionsValidation,
                       imagePartDimensionsTesting,
                       subsampledImagePartDimensionsTesting,

                       convLayersToConnectToFirstFcForMultiscaleFromAllLayerTypes,

                       initializationTechniqueClassic0orDelvingInto1,
                       activationFunctionToUseRelu0orPrelu1,
                       dropoutRatesForAllPathways, #list of sublists, one for each pathway. Each either empty or full with the dropout rates of all the layers in the path.
			
                       numberOfOutputClasses = 2,
                       dataTypeX = 'float32',
                       number_of_images_in_shared=2 #not used currently. Only to initialize a shared variable. See note where it is used.
                       ):
        """
	maxPoolingParamsStructure: The padding of the function further below adds zeros. Zeros are not good, especially if I use PreLus. So I made mine, that pads by mirroring.
	Be careful that, without this, if I have ds=2, str=1 and ignoreBorder=False, it still reduces the dimension of the image by 1. That's why I need this. To keep the dimensions stable.
	It mirrors the last elements of each dimension as many times as it is given as arg.
	"""

	self.cnnModelName = cnnModelName

	self.usingSubsampledPathway = len(nkernsSubsampled) > 0

        self.borrowFlag = borrowFlag
        self.imagePartDimensionsTraining = imagePartDimensionsTraining
        self.imagePartDimensionsValidation = imagePartDimensionsValidation
        self.imagePartDimensionsTesting = imagePartDimensionsTesting
        self.subsampledImagePartDimensionsTraining = subsampledImagePartDimensionsTraining
        self.subsampledImagePartDimensionsValidation = subsampledImagePartDimensionsValidation
        self.subsampledImagePartDimensionsTesting = subsampledImagePartDimensionsTesting

        self.batchSize = batch_size
        self.batchSizeValidation = batch_size_validation
        self.batchSizeTesting = batch_size_testing

        self.L1_reg_constant = L1_reg_constant
        self.L2_reg_constant = L2_reg_constant
        self.dataTypeX = dataTypeX
        self.nkerns = nkerns
	self.nkernsSubsampled = nkernsSubsampled
	self.nkernsZoomedIn1 = nkernsZoomedIn1
	self.kernelDimensionsFirstFcLayer = kernelDimensionsFirstFcLayer

	self.subsampleFactor = subsampleFactor
        self.patchDimensions = patchDimensions
	self.zoomedInPatchDimensions = zoomedInPatchDimensions
        self.numberOfImageChannelsPath1 = numberOfImageChannelsPath1
        self.numberOfImageChannelsPath2 = numberOfImageChannelsPath2
        self.number_of_images_in_shared = number_of_images_in_shared
        self.numberOfOutputClasses = numberOfOutputClasses
        
	self.initializationTechniqueClassic0orDelvingInto1 = initializationTechniqueClassic0orDelvingInto1
	self.dropoutRatesForAllPathways = dropoutRatesForAllPathways

	self.numberOfCentralVoxelsClassifiedPerDimension = getListOfNumberOfCentralVoxelsClassifiedPerDimension(imagePartDimensionsTraining, patchDimensions)
	self.numberOfCentralVoxelsClassifiedPerDimensionValidation = getListOfNumberOfCentralVoxelsClassifiedPerDimension(imagePartDimensionsValidation, patchDimensions)
	self.numberOfCentralVoxelsClassifiedPerDimensionTesting = getListOfNumberOfCentralVoxelsClassifiedPerDimension(imagePartDimensionsTesting, patchDimensions)
	#Batch normalization (rolling average)
	self.usingBatchNormalization = True if rollingAverageForBatchNormalizationOverThatManyBatches > 0 else False
	self.rollingAverageForBatchNormalizationOverThatManyBatches = rollingAverageForBatchNormalizationOverThatManyBatches

	self.softmaxTemperature = softmaxTemperature

        #I allocate shared-memory for training,validation and testing data,labels etc.
        #They are just zeros for now. Later, each epoch or whatever I sharedvar.set_value() and change them for training.
        #Probably it works even if I do them smaller (in dimensions) for now, as they 
        #...probably get expanded later if I sharedVar.set_value with a bigger shape.

        #The first argument used to be 'number_of_images_in_shared' but now it is just by default 2, a placeholder. When I actually .set_value loading the data, shape changes!
        trainingNiiData_x = np.zeros([number_of_images_in_shared, numberOfImageChannelsPath1, imagePartDimensionsTraining[0], imagePartDimensionsTraining[1], imagePartDimensionsTraining[2]], dtype='float32')
        trainingSubsampledData_x = trainingNiiData_x
        validationNiiData_x = trainingNiiData_x
        validationSubsampledData_x = trainingNiiData_x
        testingNiiData_x = trainingNiiData_x
        testingSubsampledData_x = trainingNiiData_x
        #trainingNiiLabels_y = np.zeros(patchesToTrainPerImagePart, dtype='float32')
        trainingNiiLabels_y = np.zeros((self.batchSize,9,9,9), dtype='float32') #9 is a placeholder. imagePartDim - halfPatch is the real thing.
        validationNiiLabels_y = trainingNiiLabels_y

        #Load them into shared variables: THIS CAN GO TO ANOTHER FUNCTION SEPARATELY!!!
        self.sharedTrainingNiiData_x = theano.shared(trainingNiiData_x, borrow = borrowFlag)
        self.sharedTrainingSubsampledData_x = theano.shared(trainingSubsampledData_x, borrow = borrowFlag)
        self.sharedValidationNiiData_x = theano.shared(validationNiiData_x, borrow = borrowFlag)
        self.sharedValidationSubsampledData_x = theano.shared(validationSubsampledData_x, borrow = borrowFlag)
        self.sharedTestingNiiData_x = theano.shared(testingNiiData_x, borrow = borrowFlag)
        self.sharedTestingSubsampledData_x = theano.shared(testingSubsampledData_x, borrow = borrowFlag)
        # When storing data on the GPU it has to be stored as floats
        # therefore we will store the labels as ``floatX`` as well
        # (``shared_y`` does exactly that). But during our computations
        # we need them as ints (we use labels as index, and if they are
        # floats it doesn't make sense) therefore instead of returning
        # ``shared_y`` we will have to cast it to int. This little hack
        # lets ous get around this issue
        self.sharedTrainingNiiLabels_y = theano.shared(trainingNiiLabels_y , borrow = borrowFlag)
        self.sharedValidationNiiLabels_y = theano.shared(validationNiiLabels_y , borrow = borrowFlag)

        #==============================

        rng = numpy.random.RandomState(23455)

        ######################
        # BUILD ACTUAL MODEL #
        ######################
        myLogger.print3("...Building the CNN model...")


	#symbolic variables needed:
	tensor5 = T.TensorType(dtype='float32', broadcastable=(False, False, False, False, False))
	x = tensor5()
	self.symbolicXForUseToReCompileTrainFunction = x
        tensor5Subsampled = T.TensorType(dtype='float32', broadcastable=(False, False, False, False, False))
	xSubsampled = tensor5Subsampled()
	self.symbolicXSubsampledForUseToReCompileTrainFunction = xSubsampled


        # Reshape matrix of rasterized images of shape (batch_size, 28 * 28)
        # to a 4D tensor, compatible with our ConvLayer
        # (28, 28) is the size of MNIST images.
	inputImageShape = (self.batchSize, numberOfImageChannelsPath1, imagePartDimensionsTraining[0], imagePartDimensionsTraining[1], imagePartDimensionsTraining[2])
	inputImageShapeValidation = (self.batchSizeValidation, numberOfImageChannelsPath1, imagePartDimensionsValidation[0], imagePartDimensionsValidation[1], imagePartDimensionsValidation[2])
	inputImageShapeTesting = (self.batchSizeTesting, numberOfImageChannelsPath1, imagePartDimensionsTesting[0], imagePartDimensionsTesting[1], imagePartDimensionsTesting[2])

        layer0_input = x.reshape(inputImageShape)
        layer0_inputValidation = x.reshape(inputImageShapeValidation)
        layer0_inputTesting = x.reshape(inputImageShapeTesting)

	if self.usingSubsampledPathway : #Using subsampled pathway.
		inputImageSubsampledShape = (self.batchSize, numberOfImageChannelsPath2, subsampledImagePartDimensionsTraining[0], subsampledImagePartDimensionsTraining[1], subsampledImagePartDimensionsTraining[2])
		inputImageSubsampledShapeValidation = (self.batchSizeValidation, numberOfImageChannelsPath2, subsampledImagePartDimensionsValidation[0], subsampledImagePartDimensionsValidation[1], subsampledImagePartDimensionsValidation[2])
		inputImageSubsampledShapeTesting = (self.batchSizeTesting, numberOfImageChannelsPath2, subsampledImagePartDimensionsTesting[0], subsampledImagePartDimensionsTesting[1], subsampledImagePartDimensionsTesting[2])

		layer0_inputSubsampled = xSubsampled.reshape(inputImageSubsampledShape)
		layer0_inputSubsampledValidation = xSubsampled.reshape(inputImageSubsampledShapeValidation)
		layer0_inputSubsampledTesting = xSubsampled.reshape(inputImageSubsampledShapeTesting)
        


	#=======================Make the FIRST (NORMAL) PATHWAY of the CNN=======================
	thisPathwayType = self.CNN_PATHWAY_NORMAL # 0 == normal
	thisPathWayNKerns = nkerns
	thisPathWayKernelDimensions = kernelDimensions
	inputImageToPathway =  layer0_input
	inputImageToPathwayInference = layer0_inputValidation
	inputImageToPathwayTesting = layer0_inputTesting

	[dimensionsOfOutputFrom1stPathway,
	dimensionsOfOutputFrom1stPathwayValidation,
	dimensionsOfOutputFrom1stPathwayTesting] = self.makeLayersOfThisPathwayAndReturnDimensionsOfOutputFM(thisPathwayType,
														thisPathWayNKerns,
														thisPathWayKernelDimensions,
														inputImageToPathway,
														inputImageToPathwayInference,
														inputImageToPathwayTesting,
														numberOfImageChannelsPath1,
														imagePartDimensionsTraining,
														imagePartDimensionsValidation,
														imagePartDimensionsTesting,
														rollingAverageForBatchNormalizationOverThatManyBatches,
														maxPoolingParamsStructure[thisPathwayType],
														initializationTechniqueClassic0orDelvingInto1,
														activationFunctionToUseRelu0orPrelu1,
														dropoutRatesForAllPathways[thisPathwayType]
														)
	myLogger.print3("DEBUG: The output of the last layer of the FIRST PATH of the cnn has dimensions:"+str(dimensionsOfOutputFrom1stPathway))

	inputToFirstFcLayer = self.cnnLayers[-1].output
	inputToFirstFcLayerInference = self.cnnLayers[-1].outputInference
	inputToFirstFcLayerTesting = self.cnnLayers[-1].outputTesting
	numberOfFmsOfInputToFirstFcLayer = dimensionsOfOutputFrom1stPathway[1]

	#====================== Make the Multi-scale-in-net connections for Path-1 ===========================	
	[numberOfFmsOfInputToFirstFcLayer, #updated after concatenations
	inputToFirstFcLayer,
	inputToFirstFcLayerInference,
	inputToFirstFcLayerTesting] = self.makeMultiscaleConnectionsForLayerType(self.CNN_PATHWAY_NORMAL,
										convLayersToConnectToFirstFcForMultiscaleFromAllLayerTypes[self.CNN_PATHWAY_NORMAL],
										numberOfFmsOfInputToFirstFcLayer,
										inputToFirstFcLayer,
										inputToFirstFcLayerInference,
										inputToFirstFcLayerTesting)


	#=======================Make the SECOND (SUBSAMPLED) PATHWAY of the CNN=============================

	if self.usingSubsampledPathway : #If there is actually a 2nd pathway in this model...
		
		thisPathwayType = self.CNN_PATHWAY_SUBSAMPLED # 1 == subsampled
		thisPathWayNKerns = nkernsSubsampled
		thisPathWayKernelDimensions = kernelDimensionsSubsampled
		inputImageToPathway =  layer0_inputSubsampled
		inputImageToPathwayInference = layer0_inputSubsampledValidation
		inputImageToPathwayTesting = layer0_inputSubsampledTesting

		[dimensionsOfOutputFrom2ndPathway,
		dimensionsOfOutputFrom2ndPathwayValidation,
		dimensionsOfOutputFrom2ndPathwayTesting] = self.makeLayersOfThisPathwayAndReturnDimensionsOfOutputFM(thisPathwayType,
															thisPathWayNKerns,
															thisPathWayKernelDimensions,
															inputImageToPathway,
															inputImageToPathwayInference,
															inputImageToPathwayTesting,
															numberOfImageChannelsPath2,
															subsampledImagePartDimensionsTraining,
															subsampledImagePartDimensionsValidation,
															subsampledImagePartDimensionsTesting,
															rollingAverageForBatchNormalizationOverThatManyBatches,
															maxPoolingParamsStructure[thisPathwayType],
															initializationTechniqueClassic0orDelvingInto1,
															activationFunctionToUseRelu0orPrelu1,
															dropoutRatesForAllPathways[thisPathwayType])
		myLogger.print3("DEBUG: Training: The output of the last layer of the SECOND PART of the cnn has dimensions:"+str(dimensionsOfOutputFrom2ndPathway))
		myLogger.print3("DEBUG: Validation: The output of the last layer of the SECOND PART of the cnn has dimensions:"+str(dimensionsOfOutputFrom2ndPathwayValidation))
		myLogger.print3("DEBUG: Testing: The output of the last layer of the SECOND PART of the cnn has dimensions:"+str(dimensionsOfOutputFrom2ndPathwayTesting))

		expandedOutputOfLastLayerOfSecondCnnPathway = self.repeatRczTheOutputOfLayerBySubsampleFactorToMatchDimensionsOfOtherFm(
													self.typesOfCnnLayers[self.CNN_PATHWAY_SUBSAMPLED][-1].output,
													dimensionsOfOutputFrom1stPathway )

		myLogger.print3("DEBUG: Training: The shape of the REPEATED output of the 2nd pathway is: " + str(expandedOutputOfLastLayerOfSecondCnnPathway))
		#For Validation with Subsampled pathway:
		expandedOutputOfLastLayerOfSecondCnnPathwayInference = self.repeatRczTheOutputOfLayerBySubsampleFactorToMatchDimensionsOfOtherFm(
													self.typesOfCnnLayers[self.CNN_PATHWAY_SUBSAMPLED][-1].outputInference,
													dimensionsOfOutputFrom1stPathwayValidation )
		myLogger.print3("DEBUG: Validation: The shape of the REPEATED output of the 2nd pathway is: " + str(expandedOutputOfLastLayerOfSecondCnnPathwayInference))
		#For Testing with Subsampled pathway:
		expandedOutputOfLastLayerOfSecondCnnPathwayTesting = self.repeatRczTheOutputOfLayerBySubsampleFactorToMatchDimensionsOfOtherFm(
													self.typesOfCnnLayers[self.CNN_PATHWAY_SUBSAMPLED][-1].outputTesting,
													dimensionsOfOutputFrom1stPathwayTesting )
		myLogger.print3("DEBUG: Testing: The shape of the REPEATED output of the 2nd pathway is: " + str(expandedOutputOfLastLayerOfSecondCnnPathwayTesting))
	
		#====================================CONCATENATE the output of the 2 cnn-pathways=============================
		inputToFirstFcLayer = T.concatenate([inputToFirstFcLayer, expandedOutputOfLastLayerOfSecondCnnPathway], axis=1)
		inputToFirstFcLayerInference = T.concatenate([inputToFirstFcLayerInference, expandedOutputOfLastLayerOfSecondCnnPathwayInference], axis=1)
		inputToFirstFcLayerTesting = T.concatenate([inputToFirstFcLayerTesting, expandedOutputOfLastLayerOfSecondCnnPathwayTesting], axis=1)
		numberOfFmsOfInputToFirstFcLayer = numberOfFmsOfInputToFirstFcLayer + dimensionsOfOutputFrom2ndPathway[1]

		#====================== Make the Multi-scale-in-net connections for Path-2 ===========================	
		[numberOfFmsOfInputToFirstFcLayer, #updated after concatenations
		inputToFirstFcLayer,
		inputToFirstFcLayerInference,
		inputToFirstFcLayerTesting] = self.makeMultiscaleConnectionsForLayerType(self.CNN_PATHWAY_SUBSAMPLED,
											convLayersToConnectToFirstFcForMultiscaleFromAllLayerTypes[self.CNN_PATHWAY_SUBSAMPLED],
											numberOfFmsOfInputToFirstFcLayer,
											inputToFirstFcLayer,
											inputToFirstFcLayerInference,
											inputToFirstFcLayerTesting)



	#=======================Make the THIRD (ZOOMED IN) PATHWAY of the CNN=======================
	if len(nkernsZoomedIn1)>0 :	
		thisPathwayType = self.CNN_PATHWAY_ZOOMED1 # 3 == ZoomedIn
		thisPathWayNKerns = nkernsZoomedIn1
		thisPathWayKernelDimensions = kernelDimensionsZoomedIn1
		
		imagePartDimensionsForZoomedPatch1Training = []; imagePartDimensionsForZoomedPatch1Validation=[]; imagePartDimensionsForZoomedPatch1Testing=[];
		for dim_i in xrange(0, 3) :
			imagePartDimensionsForZoomedPatch1Training.append(self.zoomedInPatchDimensions[dim_i] + self.numberOfCentralVoxelsClassifiedPerDimension[dim_i] -1)
			imagePartDimensionsForZoomedPatch1Validation.append(self.zoomedInPatchDimensions[dim_i] + self.numberOfCentralVoxelsClassifiedPerDimensionValidation[dim_i] -1)
			imagePartDimensionsForZoomedPatch1Testing.append(self.zoomedInPatchDimensions[dim_i] + self.numberOfCentralVoxelsClassifiedPerDimensionTesting[dim_i] -1)

		inputImageToPathway =  self.getMiddlePartOfFms(layer0_input, inputImageShape, imagePartDimensionsForZoomedPatch1Training)
		inputImageToPathwayInference = self.getMiddlePartOfFms(layer0_inputValidation, inputImageShapeValidation, imagePartDimensionsForZoomedPatch1Validation)
		inputImageToPathwayTesting = self.getMiddlePartOfFms(layer0_inputTesting, inputImageShapeTesting, imagePartDimensionsForZoomedPatch1Testing)

		[dimensionsOfOutputFromZoomed1Pathway,
		dimensionsOfOutputFromZoomed1PathwayValidation,
		dimensionsOfOutputFromZoomed1PathwayTesting] = self.makeLayersOfThisPathwayAndReturnDimensionsOfOutputFM(thisPathwayType,
															thisPathWayNKerns,
															thisPathWayKernelDimensions,
															inputImageToPathway,
															inputImageToPathwayInference,
															inputImageToPathwayTesting,
															numberOfImageChannelsPath1,
															imagePartDimensionsForZoomedPatch1Training,
															imagePartDimensionsForZoomedPatch1Validation,
															imagePartDimensionsForZoomedPatch1Testing,
															rollingAverageForBatchNormalizationOverThatManyBatches,
															maxPoolingParamsStructure[thisPathwayType],
															initializationTechniqueClassic0orDelvingInto1,
															activationFunctionToUseRelu0orPrelu1,
															dropoutRatesForAllPathways[thisPathwayType])
		#====================================CONCATENATE the output of the ZoomedIn1 pathway=============================
		inputToFirstFcLayer = T.concatenate([inputToFirstFcLayer, self.typesOfCnnLayers[thisPathwayType][-1].output], axis=1)
		inputToFirstFcLayerInference = T.concatenate([inputToFirstFcLayerInference, self.typesOfCnnLayers[thisPathwayType][-1].outputInference], axis=1)
		inputToFirstFcLayerTesting = T.concatenate([inputToFirstFcLayerTesting, self.typesOfCnnLayers[thisPathwayType][-1].outputTesting], axis=1)
		numberOfFmsOfInputToFirstFcLayer = numberOfFmsOfInputToFirstFcLayer + dimensionsOfOutputFromZoomed1Pathway[1]



        #======================= Make the Fully Connected Layers =======================
	"""
	THIS USED TO BE AUTOMATIC, BUT WITH MAX POOLING IT GOT COMPLICATED, AND NOW I DEFINE IT.	
	#Calculate the kernel dimensions of the first FC layer such that it convolves everything and I end up with only 1 feature per patch.
        firstFcLayerAfterConcatenationKernelShape = [patchDimensions[0],patchDimensions[1],patchDimensions[2]]
        for layer_i in xrange(len(nkerns)) :
            for dim_i in xrange(len(patchDimensions)) :
                firstFcLayerAfterConcatenationKernelShape[dim_i] += - kernelDimensions[layer_i][dim_i] + 1
	"""
	firstFcLayerAfterConcatenationKernelShape = self.kernelDimensionsFirstFcLayer

        myLogger.print3("DEBUG: In order to be fully connected, the shape of the kernel of the first FC layer is : " + str(firstFcLayerAfterConcatenationKernelShape) )    	
	
	inputOfFcPathwayImagePartDimensionsTraining = [	dimensionsOfOutputFrom1stPathway[2],
						dimensionsOfOutputFrom1stPathway[3],
						dimensionsOfOutputFrom1stPathway[4]]
	inputOfFcPathwayImagePartDimensionsValidation = [dimensionsOfOutputFrom1stPathwayValidation[2],
							dimensionsOfOutputFrom1stPathwayValidation[3],
							dimensionsOfOutputFrom1stPathwayValidation[4]]
	inputOfFcPathwayImagePartDimensionsTesting = [	dimensionsOfOutputFrom1stPathwayTesting[2],
							dimensionsOfOutputFrom1stPathwayTesting[3],
							dimensionsOfOutputFrom1stPathwayTesting[4]]

	if len(fcLayersFMs)>0 : 
		thisPathwayType = self.CNN_PATHWAY_FC # 2 == normal
		thisPathWayNKerns = fcLayersFMs
		thisPathWayKernelDimensions = [firstFcLayerAfterConcatenationKernelShape]
		for fcLayer_i in xrange(1,len(fcLayersFMs)) :
			thisPathWayKernelDimensions.append([1,1,1])
		inputImageToPathway =  inputToFirstFcLayer
		inputImageToPathwayInference =  inputToFirstFcLayerInference
		inputImageToPathwayTesting =  inputToFirstFcLayerTesting
		

		myLogger.print3("DEBUG: shape Of Input Image To FC Pathway:" + str(inputOfFcPathwayImagePartDimensionsTraining) )
		[dimensionsOfOutputFeatureMapFromExtraFcLayersPathway,
		dimensionsOfOutputFeatureMapFromExtraFcLayersPathwayValidation,
		dimensionsOfOutputFeatureMapFromExtraFcLayersPathwayTesting] = self.makeLayersOfThisPathwayAndReturnDimensionsOfOutputFM(thisPathwayType,
															thisPathWayNKerns,
															thisPathWayKernelDimensions,
															inputImageToPathway,
															inputImageToPathwayInference,
															inputImageToPathwayTesting,
															numberOfFmsOfInputToFirstFcLayer,
															inputOfFcPathwayImagePartDimensionsTraining,
															inputOfFcPathwayImagePartDimensionsValidation,
															inputOfFcPathwayImagePartDimensionsTesting,
															rollingAverageForBatchNormalizationOverThatManyBatches,
															maxPoolingParamsStructure[thisPathwayType],
															initializationTechniqueClassic0orDelvingInto1,
															activationFunctionToUseRelu0orPrelu1,
															dropoutRatesForAllPathways[thisPathwayType])

		inputImageForFinalClassificationLayer = self.fcLayers[-1].output
		inputImageForFinalClassificationLayerInference = self.fcLayers[-1].outputInference
		inputImageForFinalClassificationLayerTesting = self.fcLayers[-1].outputTesting
		shapeOfInputImageForFinalClassificationLayer = dimensionsOfOutputFeatureMapFromExtraFcLayersPathway
		shapeOfInputImageForFinalClassificationLayerValidation = dimensionsOfOutputFeatureMapFromExtraFcLayersPathwayValidation
		shapeOfInputImageForFinalClassificationLayerTesting = dimensionsOfOutputFeatureMapFromExtraFcLayersPathwayTesting
		filterShapeForFinalClassificationLayer = [self.numberOfOutputClasses, fcLayersFMs[-1], 1, 1, 1]
	else : #there is no extra FC layer, just the final FC-softmax.
		inputImageForFinalClassificationLayer = inputToFirstFcLayer
		inputImageForFinalClassificationLayerInference = inputToFirstFcLayerInference
		inputImageForFinalClassificationLayerTesting = inputToFirstFcLayerTesting
		shapeOfInputImageForFinalClassificationLayer = [self.batchSize, numberOfFmsOfInputToFirstFcLayer] + inputOfFcPathwayImagePartDimensionsTraining
		shapeOfInputImageForFinalClassificationLayerValidation = [self.batchSizeValidation, numberOfFmsOfInputToFirstFcLayer] + inputOfFcPathwayImagePartDimensionsValidation
		shapeOfInputImageForFinalClassificationLayerTesting = [self.batchSizeTesting, numberOfFmsOfInputToFirstFcLayer] + inputOfFcPathwayImagePartDimensionsTesting
		filterShapeForFinalClassificationLayer = [self.numberOfOutputClasses, numberOfFmsOfInputToFirstFcLayer] + firstFcLayerAfterConcatenationKernelShape


        #======================Make the FINAL FC CLASSIFICATION LAYER ===================================
	myLogger.print3("DEBUG: Filter Shape of the final-FC-classification Layer: " + str(filterShapeForFinalClassificationLayer))
	#The last classification FC layer + softmax.
	dropoutRateForClassificationLayer = 0 if dropoutRatesForAllPathways[self.CNN_PATHWAY_FC] == [] else dropoutRatesForAllPathways[self.CNN_PATHWAY_FC][-1]
        classificationLayer = ConvLayerWithSoftmax(
            rng,
            input = inputImageForFinalClassificationLayer,
            inputInferenceBn=inputImageForFinalClassificationLayerInference,
            inputTestingBn=inputImageForFinalClassificationLayerTesting,		    
            image_shape = shapeOfInputImageForFinalClassificationLayer,
            image_shapeValidation=shapeOfInputImageForFinalClassificationLayerValidation,
            image_shapeTesting=shapeOfInputImageForFinalClassificationLayerTesting,
            filter_shape = filterShapeForFinalClassificationLayer,
            poolsize=(0, 0),
            initializationTechniqueClassic0orDelvingInto1 = initializationTechniqueClassic0orDelvingInto1,
            dropoutRate = dropoutRateForClassificationLayer,
            softmaxTemperature = self.softmaxTemperature
        )
        self.fcLayers.append(classificationLayer)
        self.classificationLayer = classificationLayer


	#======== Make and compile the training, validation, testing and visualisation functions. ==========
	self.compileNewTrainFunction(myLogger, "all", learning_rate, 
				sgd0orAdam1orRmsProp2,
					classicMomentum0OrNesterov1,
					momentum,
					momentumTypeNONNormalized0orNormalized1, 
					b1ParamForAdam,
					b2ParamForAdam,
					epsilonForAdam,
					rhoParamForRmsProp,
					epsilonForRmsProp,
				costFunctionLetter)
	self.compileNewValidationFunction(myLogger)
	#self.compileNewTestFunction(myLogger)
	#self.compileNewVisualisationFunctionForWhole(myLogger)
	self.compileNewTestAndVisualisationFunctionForWhole(myLogger)

        myLogger.print3("Finished. Created the CNN's model")
