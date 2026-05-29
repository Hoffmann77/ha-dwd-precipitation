---
name: Bug report
about: Create a report to help us improve
title: ''
labels: bug
assignees: Hoffmann77

---

name: Report an issue
description: Report an issue.
body:
  - type: markdown
    attributes:
      value: |
        This issue form is for reporting bugs only!

  - type: textarea
    validations:
      required: true
    attributes:
      label: The problem
      description: >-
        Describe the issue you are experiencing here, to communicate to the
        maintainers. Tell us what you were trying to do and what happened.

        Provide a clear and concise description of what the problem is.
  - type: markdown
    attributes:
      value: |
        ## Environment
  - type: input
    id: version
    validations:
      required: true
    attributes:
      label: What version of Home Assistant Core has the issue?
      placeholder: core-
      description: >
        Can be found in: [Settings ⇒ System ⇒ Repairs ⇒ Three Dots in Upper Right ⇒ System information](https://my.home-assistant.io/redirect/system_health/).

        [![Open your Home Assistant instance and show the system information.](https://my.home-assistant.io/badges/system_health.svg)](https://my.home-assistant.io/redirect/system_health/)
  - type: input
    attributes:
      label: What was the last working version of Home Assistant Core?
      placeholder: core-
      description: >
        If known, otherwise leave blank.
  - type: dropdown
    validations:
      required: true
    attributes:
      label: What type of installation are you running?
      description: >
        Can be found in: [Settings ⇒ System ⇒ Repairs ⇒ Three Dots in Upper Right ⇒ System information](https://my.home-assistant.io/redirect/system_health/).

        [![Open your Home Assistant instance and show the system information.](https://my.home-assistant.io/badges/system_health.svg)](https://my.home-assistant.io/redirect/system_health/)
      options:
        - Home Assistant OS
        - Home Assistant Container
        - Home Assistant Supervised
        - Home Assistant Core
 
  - type: markdown
    attributes:
      value: |
        # Details
 - type: textarea
    attributes:
      label: Anything in the logs that might be useful for us?
      description: For example, error message, or stack traces.
      render: txt
  - type: textarea
    attributes:
      label: Additional information
      description: >
        If you have any additional information for us, use the field below.
